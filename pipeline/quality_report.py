"""Data-quality and currency checks for Hudson County tax data.

Inputs (produced by the fetch/parse steps):
  data/interim/modiv_hudson_<year>.csv   MOD-IV tax list, one per list year
  data/raw/state/GTRhistory.xlsx          official general tax rates 1997-2025
  data/raw/state/<year>AvgResStat.pdf     official average residential stats
  data/raw/njogis/parcels_hudson.csv      NJOGIS parcel composite (hosted service)
  data/interim/jc_bill_sample.csv         live Jersey City bills for a sample of parcels

Writes data/interim/quality/*.csv and prints a summary.
"""
import json
import re
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
INTERIM = ROOT / "data" / "interim"
STATE = ROOT / "data" / "raw" / "state"
OUT = INTERIM / "quality"
YEARS = range(2021, 2027)
JC = "0906"


def load_modiv(year):
    d = pd.read_csv(INTERIM / f"modiv_hudson_{year}.csv", dtype=str, low_memory=False).fillna("")
    for c in ("net_value", "prior_yr_net_value", "land_value", "improvement_value"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    for c in ("last_year_tax", "current_year_tax"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["list_year"] = year
    d["abatement"] = d.exempt_statute.str.replace(";", ":").str.replace("-", ":", n=1).map(
        lambda s: "long_term_40A20" if s.startswith("40A:20") else ("five_year_40A21" if s.startswith("40A:21") else "")
    )
    return d


def load_rates():
    raw = pd.read_excel(STATE / "GTRhistory.xlsx", sheet_name=0, header=None)
    years = raw.iloc[0]
    rows = raw[raw[0].astype(str).str.strip().str.upper() == "HUDSON"]
    out = []
    for _, r in rows.iterrows():
        code = str(r[1]).strip().zfill(4)
        for col in range(3, raw.shape[1]):
            y = years[col]
            if pd.notna(y) and int(y) >= 2018:
                out.append({"county_district": code, "year": int(y), "general_rate": float(r[col])})
    return pd.DataFrame(out)


def load_avg_res_stats():
    out = []
    for y in YEARS:
        pdf = STATE / f"{y}AvgResStat.pdf"
        if not pdf.exists():
            continue
        text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
        for line in text.splitlines():
            m = re.match(r"^(09(?:0[1-9]|1[0-2]))\s+(.+?)\s{2,}([\d,]+)\s+\$([\d,]+)\s+(\$[\d,]+)?", line)
            if m:
                out.append({
                    "county_district": m.group(1), "year": y, "state_line_items": int(m.group(3).replace(",", "")),
                    "state_avg_assessment": int(m.group(4).replace(",", "")),
                    "state_avg_tax": int(m.group(5).strip("$").replace(",", "")) if m.group(5) else None,
                })
    return pd.DataFrame(out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lists = {y: load_modiv(y) for y in YEARS if (INTERIM / f"modiv_hudson_{y}.csv").exists()}
    rates = load_rates()
    avg = load_avg_res_stats()
    summary = {}

    # 1. Completeness per list year and town
    comp = []
    for y, d in lists.items():
        for code, g in d.groupby("county_district"):
            comp.append({
                "list_year": y, "county_district": code, "municipality": g.municipality.iloc[0],
                "records": len(g), "unique_pins": g.pin.nunique(),
                "duplicate_pins": int(g.pin.duplicated().sum()),
                "missing_class": int((g.property_class == "").sum()),
                "zero_net_value_taxable_class": int(((g.net_value.fillna(0) == 0) & ~g.property_class.str.startswith("15")).sum()),
                "has_last_year_tax": round((g.last_year_tax.fillna(0) > 0).mean(), 4),
                "has_current_year_tax": round((g.current_year_tax.fillna(0) > 0).mean(), 4),
                "class2_count": int((g.property_class == "2").sum()),
                "abated_40A20": int((g.abatement == "long_term_40A20").sum()),
                "abated_40A21": int((g.abatement == "five_year_40A21").sum()),
                "max_transaction_date": max((t for t in g.transaction_date if len(t) == 6),
                                            key=lambda t: (t[4:], t[:4]), default=""),
            })
    comp = pd.DataFrame(comp)
    comp.to_csv(OUT / "completeness_by_year_town.csv", index=False)

    # 2. Reconcile against official state averages (class 2 residential)
    recon = []
    for y, d in lists.items():
        r2 = d[d.property_class == "2"]
        for code, g in r2.groupby("county_district"):
            rate = rates[(rates.county_district == code) & (rates.year == y)].general_rate
            rate = float(rate.iloc[0]) if len(rate) else None
            recon.append({
                "year": y, "county_district": code, "municipality": g.municipality.iloc[0],
                "our_line_items": len(g), "our_avg_assessment": round(g.net_value.mean()),
                "general_rate": rate,
                "our_avg_tax_est": round(g.net_value.mean() * rate / 100) if rate else None,
            })
    recon = pd.DataFrame(recon).merge(avg, on=["county_district", "year"], how="left")
    recon["assessment_diff_pct"] = (recon.our_avg_assessment / recon.state_avg_assessment - 1) * 100
    recon["tax_diff_pct"] = (recon.our_avg_tax_est / recon.state_avg_tax - 1) * 100
    recon.to_csv(OUT / "reconcile_vs_state_averages.csv", index=False)

    # 3. Recorded tax (last_year_tax in list Y+1) vs assessment x official rate for year Y
    taxchk = []
    for y in YEARS:
        if y + 1 not in lists:
            continue
        d = lists[y + 1]
        d = d[(d.last_year_tax > 0) & (d.prior_yr_net_value > 0) & (d.abatement == "")]
        for code, g in d.groupby("county_district"):
            rate = rates[(rates.county_district == code) & (rates.year == y)].general_rate
            if not len(rate):
                continue
            implied = g.last_year_tax / g.prior_yr_net_value * 100
            within = ((implied - rate.iloc[0]).abs() <= 0.01).mean()
            taxchk.append({
                "tax_year": y, "county_district": code, "municipality": g.municipality.iloc[0],
                "parcels_checked": len(g), "official_rate": rate.iloc[0],
                "median_implied_rate": round(implied.median(), 4),
                "share_within_0.01_of_rate": round(within, 4),
            })
    taxchk = pd.DataFrame(taxchk)
    taxchk.to_csv(OUT / "recorded_tax_vs_official_rate.csv", index=False)

    # 4. Parcel continuity year to year
    cont = []
    ys = sorted(lists)
    for a, b in zip(ys, ys[1:]):
        pa, pb = set(lists[a].pin), set(lists[b].pin)
        cont.append({"from": a, "to": b, "kept": len(pa & pb), "dropped": len(pa - pb), "added": len(pb - pa)})
    pd.DataFrame(cont).to_csv(OUT / "parcel_continuity.csv", index=False)

    # 5. Jersey City tax history from the state lists (tax year = list year - 1)
    hist = []
    for y, d in lists.items():
        g = d[(d.county_district == JC)]
        hist.append({
            "tax_year": y - 1, "source": f"MOD-IV {y} last_year_tax",
            "class2_parcels": int((g.property_class == "2").sum()),
            "class2_median_tax": g[g.property_class == "2"].last_year_tax.median(),
            "total_tax_all_parcels": round(g.last_year_tax.sum()),
        })
    pd.DataFrame(hist).to_csv(OUT / "jc_tax_history_from_modiv.csv", index=False)

    # 6. NJOGIS hosted composite: which list year does it reflect?
    njogis_path = ROOT / "data" / "raw" / "njogis" / "parcels_hudson.csv"
    if njogis_path.exists():
        g = pd.read_csv(njogis_path, dtype=str, low_memory=False).fillna("")
        g["LAST_YR_TX"] = pd.to_numeric(g.LAST_YR_TX, errors="coerce")
        g["NET_VALUE"] = pd.to_numeric(g.NET_VALUE, errors="coerce")
        g = g.drop_duplicates("PAMS_PIN")
        match = {}
        for y, d in lists.items():
            m = g.merge(d.drop_duplicates("pin")[["pin", "last_year_tax", "net_value"]],
                        left_on="PAMS_PIN", right_on="pin")
            match[y] = {
                "joined": len(m),
                "last_year_tax_equal": round(((m.LAST_YR_TX - m.last_year_tax).abs() < 0.01).mean(), 4),
                "net_value_equal": round((m.NET_VALUE == m.net_value).mean(), 4),
            }
        summary["njogis_rows"] = len(g)
        summary["njogis_matches_modiv_list_year"] = match
        summary["njogis_dates"] = {
            "max_PCLLASTUPD": g.PCLLASTUPD.max(), "max_PCL_PBDATE": g.PCL_PBDATE.max(),
        }

    # 7. Live sample of actual Jersey City bills
    sample_path = INTERIM / "jc_bill_sample.csv"
    if sample_path.exists():
        s = pd.read_csv(sample_path)
        s = s[s.found == True].copy()  # noqa: E712
        for c in ("modiv_last_year_tax", "billed_2025", "billed_2026", "city_net_taxable", "modiv_net_value",
                  "q1_2026", "q2_2026", "q3_2026", "q4_2026"):
            s[c] = pd.to_numeric(s[c], errors="coerce")
        s["modiv_2025_matches_city"] = (s.modiv_last_year_tax - s.billed_2025).abs() <= 1
        s["assessment_matches_city"] = s.modiv_net_value == s.city_net_taxable
        s["pct_change_2025_2026"] = (s.billed_2026 / s.billed_2025 - 1) * 100
        s["implied_2026_rate"] = s.billed_2026 / s.city_net_taxable * 100
        s["h2_vs_h1_2026_pct"] = ((s.q3_2026 + s.q4_2026) / (s.q1_2026 + s.q2_2026) - 1) * 100
        s.to_csv(OUT / "jc_live_bill_check.csv", index=False)
        by = s.groupby("stratum").agg(
            n=("pin", "count"),
            modiv_2025_matches=("modiv_2025_matches_city", "mean"),
            assessment_matches=("assessment_matches_city", "mean"),
            median_change_pct=("pct_change_2025_2026", "median"),
            median_implied_2026_rate=("implied_2026_rate", "median"),
            median_h2_vs_h1_pct=("h2_vs_h1_2026_pct", "median"),
        )
        by.to_csv(OUT / "jc_live_bill_check_by_stratum.csv")
        summary["live_sample_found"] = int(len(s))

    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    for f in sorted(OUT.glob("*.csv")):
        print(f"\n=== {f.name}")
        print(pd.read_csv(f).to_string(index=False, max_rows=80))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
