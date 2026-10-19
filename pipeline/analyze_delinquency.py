"""Delinquency analytics for one town: owner type x property type x severity, plus existing liens.

  python pipeline/analyze_delinquency.py --export data/portal/export/wipp --town hoboken \
      --modiv data/interim/modiv_hudson_2026.csv --out data/portal/analytics/hoboken

Input is an `extract_bills.py export` folder (accounts.csv must include the delinquency columns,
i.e. an export made after delinquency tracking was added). The MOD-IV list is optional and only
used to split non-condo homes into single-family vs 2-4 family.

Writes (owner names appear only in delinquent_properties.csv):
  summary.json                 headline numbers
  by_owner_type.csv            accounts, delinquent, rate, past-due $, liens per owner type
  by_property_type.csv         same per property type
  owner_x_property.csv         delinquency rate for each owner type x property type
  severity_by_owner_type.csv   counts per severity level per owner type
  delinquent_properties.csv    every delinquent / liened property with its classification
  report.md                    the tables above, readable
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from owners import classify_all  # noqa: E402
from portals.registry import TOWNS  # noqa: E402

SEVERITY_ORDER = ["current", "1_quarter", "2_3_quarters", "4plus_quarters", "lien"]
OWNER_ORDER = ["owner_occupied", "individual_investor", "small_llc", "corporate", "trust_estate",
               "public_nonprofit", "unknown"]
PROPERTY_ORDER = ["condo", "single_family", "two_to_four_family", "home_units_unknown", "apartment_5plus", "commercial",
                  "vacant_land", "exempt", "no_class_on_file", "other"]
RECENT_LIEN_YEARS = 5   # liens sold within this many years count as recent; older ones are legacy city-held liens


def property_type(pin, prop_class, dwellings):
    cls = (prop_class or "").strip().upper()
    qualifier = pin.split("_")[3] if pin.count("_") >= 3 else ""
    if not cls:
        # billed accounts with no class or assessment (not on the MOD-IV list): typically abatement/PILOT billing
        return "no_class_on_file"
    if cls.startswith("15"):
        return "exempt"
    if cls == "1":
        return "vacant_land"
    if cls in ("4A", "4B"):
        return "commercial"
    if cls == "4C":
        return "apartment_5plus"
    if cls == "2":
        if qualifier.startswith("C"):
            return "condo"
        if dwellings == 1:
            return "single_family"
        # class 2 is residential with at most 4 units, so 2+ dwellings means a 2-4 family house
        return "two_to_four_family" if dwellings and dwellings >= 2 else "home_units_unknown"
    return "other"


def newest_lien_year(liens_json):
    try:
        years = [int(str(x.get("sale_date") or "")[:4]) for x in json.loads(liens_json or "[]")
                 if str(x.get("sale_date") or "")[:4].isdigit()]
    except (ValueError, TypeError, AttributeError):
        return 0
    return max(years, default=0)


def load_dwellings(modiv_csv, county_district):
    if not modiv_csv or not Path(modiv_csv).exists():
        return {}
    m = pd.read_csv(modiv_csv, dtype=str, usecols=["pin", "county_district", "no_of_dwellings", "building_description"],
                    low_memory=False).fillna("")
    m = m[m.county_district == county_district]
    units = pd.to_numeric(m.no_of_dwellings.str.strip(), errors="coerce")
    from_desc = pd.to_numeric(m.building_description.str.extract(r"(\d+)U")[0], errors="coerce")
    units = units.where(units > 0, from_desc)
    return dict(zip(m.pin, units))


def analyze(accounts, dwellings):
    """accounts: DataFrame of one town's accounts.csv rows. Returns an annotated DataFrame."""
    a = accounts[accounts.status.isin(["done", "no_bills"])].copy().reset_index(drop=True)
    records = a.astype(object).where(a.notna() & (a != ""), None).to_dict("records")
    owner = classify_all(records)
    a["owner_type"] = [o for o, _ in owner]
    a["owner_portfolio"] = [n for _, n in owner]
    a["dwellings"] = a.pin.map(dwellings)
    a["property_type"] = [property_type(p, c, None if pd.isna(d) else int(d))
                          for p, c, d in zip(a.pin, a.property_class, a.dwellings)]
    for col in ("past_due_amount", "past_due_bills", "lien_count", "lien_open_balance"):
        a[col] = pd.to_numeric(a.get(col), errors="coerce").fillna(0)
    a["severity"] = a.delinquency_level.fillna("").replace("", "unknown")
    a["has_lien"] = a.lien_count > 0
    a["newest_lien_year"] = [newest_lien_year(j) for j in a.get("liens_json", pd.Series([""] * len(a)))]
    newest = pd.to_datetime(a.fetched_at, errors="coerce", utc=True).dt.year.max()
    a["has_recent_lien"] = a.has_lien & (a.newest_lien_year >= (newest or 0) - RECENT_LIEN_YEARS)
    a["tax_sale"] = a.get("pending_tax_sale", pd.Series(dtype=str)).astype(str).isin(["1", "1.0", "True", "true"])
    a["in_bankruptcy"] = a.get("bankruptcy", pd.Series(dtype=str)).astype(str).isin(["1", "1.0", "True", "true"])
    a["delinquent"] = a.severity.isin(SEVERITY_ORDER[1:])
    a["amount_owed"] = a.past_due_amount + a.lien_open_balance
    return a


def group_table(a, key, order):
    taxable = a[a.property_type != "exempt"] if key != "property_type" else a
    g = taxable.groupby(key)
    t = pd.DataFrame({
        "accounts": g.size(),
        "delinquent": g.delinquent.sum(),
        "with_open_lien": g.has_lien.sum(),
        "with_recent_lien": g.has_recent_lien.sum(),
        "past_due_$": g.past_due_amount.sum().round(0),
        "lien_open_balance_$": g.lien_open_balance.sum().round(0),
    })
    for col in ("accounts", "delinquent", "with_open_lien", "with_recent_lien"):
        t[col] = t[col].astype(int)
    t["delinquency_rate_%"] = (t.delinquent / t.accounts * 100).round(2)
    t["share_of_delinquent_%"] = (t.delinquent / max(1, t.delinquent.sum()) * 100).round(1)
    return t.reindex([k for k in order if k in t.index])


def to_markdown(df, index_label):
    cols = [index_label, *df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    def fmt(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer():
            return f"{int(v):,}"
        return f"{v:,.0f}" if isinstance(v, float) and abs(v) >= 1000 else str(v)
    for row in df.itertuples():   # itertuples keeps each column's dtype (iterrows upcasts ints to float)
        cells = [str(row[0])] + [fmt(v) for v in row[1:]]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True, help="export folder containing accounts.csv")
    ap.add_argument("--town", required=True, choices=TOWNS)
    ap.add_argument("--modiv", help="MOD-IV list CSV (for single vs 2-4 family)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cd = TOWNS[args.town]["county_district"]
    accounts = pd.read_csv(Path(args.export) / "accounts.csv", dtype=str, low_memory=False).fillna("")
    accounts = accounts[accounts.county_district == cd]
    if "delinquency_level" not in accounts.columns:
        sys.exit("accounts.csv has no delinquency columns: use an export made after delinquency tracking was added")
    a = analyze(accounts, load_dwellings(args.modiv, cd))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    known = a[a.severity != "unknown"]
    by_owner = group_table(known, "owner_type", OWNER_ORDER)
    by_prop = group_table(known, "property_type", PROPERTY_ORDER)
    taxable = known[known.property_type != "exempt"]
    cross = (taxable.pivot_table(index="owner_type", columns="property_type", values="delinquent", aggfunc="mean") * 100).round(2)
    cross = cross.reindex(index=[o for o in OWNER_ORDER if o in cross.index],
                          columns=[p for p in PROPERTY_ORDER if p in cross.columns])
    counts = taxable.pivot_table(index="owner_type", columns="property_type", values="pin", aggfunc="count")
    sev = taxable.pivot_table(index="owner_type", columns="severity", values="pin", aggfunc="count", fill_value=0)
    sev = sev.reindex(index=[o for o in OWNER_ORDER if o in sev.index],
                      columns=[s for s in SEVERITY_ORDER if s in sev.columns], fill_value=0)

    by_owner.to_csv(out / "by_owner_type.csv")
    by_prop.to_csv(out / "by_property_type.csv")
    cross.to_csv(out / "owner_x_property.csv")
    sev.to_csv(out / "severity_by_owner_type.csv")
    cols = ["pin", "property_location", "property_type", "dwellings", "owner_type", "owner_portfolio", "owner_name",
            "mailing_address", "mailing_city_state", "mailing_zip", "severity", "past_due_bills", "past_due_amount",
            "oldest_past_due", "lien_count", "newest_lien_year", "lien_open_balance", "liens_json", "tax_sale", "in_bankruptcy",
            "net_taxable", "fetched_at"]
    flagged = a[a.delinquent | a.has_lien | a.tax_sale | a.in_bankruptcy].sort_values("amount_owed", ascending=False)
    flagged[[c for c in cols if c in flagged.columns]].to_csv(out / "delinquent_properties.csv", index=False,
                                                            quoting=csv.QUOTE_MINIMAL)

    summary = {
        "town": TOWNS[args.town]["name"],
        "accounts_analyzed": int(len(known)),
        "accounts_without_delinquency_data": int((a.severity == "unknown").sum()),
        "as_of_range": [str(known.fetched_at.min()), str(known.fetched_at.max())] if len(known) else None,
        "delinquent": int(known.delinquent.sum()),
        "delinquency_rate_taxable_%": round(float(taxable.delinquent.mean() * 100), 2) if len(taxable) else None,
        "past_due_total_$": round(float(known.past_due_amount.sum()), 2),
        "properties_with_open_liens": int(known.has_lien.sum()),
        f"properties_with_lien_sold_in_last_{RECENT_LIEN_YEARS}_years": int(known.has_recent_lien.sum()),
        "lien_open_balance_total_$": round(float(known.lien_open_balance.sum()), 2),
        "delinquent_with_existing_lien": int((known.delinquent & known.has_lien).sum()),
        "in_tax_sale": int(known.tax_sale.sum()),
        "in_bankruptcy": int(known.in_bankruptcy.sum()),
        "severity_counts": {k: int(v) for k, v in known.severity.value_counts().items()},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))

    report = [f"# {summary['town']} tax delinquency", "",
              f"Accounts analyzed: {summary['accounts_analyzed']:,} (as of {summary['as_of_range']})", "",
              "Delinquent = a property-tax bill still unpaid more than 10 days after its due date, or an open "
              "tax-sale lien. Rates are delinquent accounts / all accounts in the group (tax-exempt excluded "
              "from the owner table).", "",
              "## By owner type", to_markdown(by_owner, "owner_type"), "",
              "## By property type", to_markdown(by_prop, "property_type"), "",
              "## Delinquency rate %, owner type x property type (taxable)", to_markdown(cross.fillna("-"), "owner_type"), "",
              "Accounts per cell:", to_markdown(counts.reindex(index=cross.index, columns=cross.columns).fillna(0).astype(int),
                                                "owner_type"), "",
              "## Severity by owner type (taxable)", to_markdown(sev, "owner_type"), "",
              "## Headline", "```", json.dumps(summary, indent=2), "```"]
    (out / "report.md").write_text("\n".join(report))
    print("\n".join(report))


if __name__ == "__main__":
    main()
