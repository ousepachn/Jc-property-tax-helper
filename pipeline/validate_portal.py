"""Check extracted portal data against the state MOD-IV 2026 tax list.

  python pipeline/validate_portal.py [--db data/portal/bills.sqlite] [--modiv data/interim/modiv_hudson_2026.csv]

For each town: how many portal accounts join to a MOD-IV parcel, whether assessments agree,
whether 2025 billed totals equal MOD-IV's last_year_tax (2025), and what 2026 looks like
(implied rate, change vs 2025, second-half vs first-half bills).
"""
import argparse
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def load(db_path, modiv_path):
    db = sqlite3.connect(db_path)
    accts = pd.read_sql("SELECT * FROM accounts WHERE status IN ('done','no_bills')", db)
    bills = pd.read_sql("SELECT * FROM bills", db)
    modiv = pd.read_csv(modiv_path, dtype=str, low_memory=False,
                        usecols=["pin", "county_district", "property_class", "net_value", "last_year_tax", "exempt_statute"])
    modiv = modiv[modiv.county_district.isin(accts.county_district.unique())].drop_duplicates("pin")
    for c in ("net_value", "last_year_tax"):
        modiv[c] = pd.to_numeric(modiv[c], errors="coerce")
    return accts, bills, modiv


def annual(bills):
    b = bills.copy()
    b["is_tax"] = b.kind == "tax"
    b["h1"] = b.is_tax & b.quarter.isin([1, 2])
    b["h2"] = b.is_tax & b.quarter.isin([3, 4])
    g = b.groupby(["pin", "tax_year"])
    return pd.DataFrame({
        "total": g.apply(lambda x: x.amount[x.category == "property_tax"].sum()),
        "tax": g.apply(lambda x: x.amount[x.is_tax].sum()),
        "h1": g.apply(lambda x: x.amount[x.h1].sum()),
        "h2": g.apply(lambda x: x.amount[x.h2].sum()),
        "quarters": g.apply(lambda x: x.quarter[x.is_tax].nunique()),
    }).reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=ROOT / "data" / "portal" / "bills.sqlite")
    ap.add_argument("--modiv", default=ROOT / "data" / "interim" / "modiv_hudson_2026.csv")
    ap.add_argument("--out", default=None, help="optional CSV of per-parcel comparisons")
    args = ap.parse_args()

    accts, bills, modiv = load(args.db, args.modiv)
    a = annual(bills)
    y25 = a[a.tax_year == 2025].set_index("pin")
    y26 = a[(a.tax_year == 2026) & (a.quarters == 4)].set_index("pin")

    m = accts.merge(modiv, on="pin", how="left", suffixes=("", "_modiv"))
    m["in_modiv"] = m.net_value.notna()
    m["assessment_match"] = (m.net_taxable - m.net_value).abs() < 1
    m["tax25"] = m.pin.map(y25.total)
    m["tax25_match"] = (m.tax25 - m.last_year_tax).abs() <= 1
    m["tax26"] = m.pin.map(y26.total)
    m["change_pct"] = (m.tax26 / m.tax25 - 1) * 100
    base = m.net_taxable.where(m.net_taxable > 0, m.net_value)
    m["implied_rate_26"] = m.pin.map(y26.tax) / base * 100
    m["h2_vs_h1_pct"] = (m.pin.map(y26.h2) / m.pin.map(y26.h1) - 1) * 100

    taxed = m[m.status == "done"]
    rows = []
    for cd, g in m.groupby("county_district"):
        t = taxed[taxed.county_district == cd]
        has25 = t[t.tax25.notna() & (t.last_year_tax > 0)]
        rows.append({
            "town": cd,
            "accounts": len(g),
            "with_bills": len(t),
            "joined_to_modiv": f"{g.in_modiv.mean():.1%}",
            "assessment_match": f"{t[t.net_taxable.notna() & t.in_modiv].assessment_match.mean():.1%}"
            if (t.net_taxable.notna() & t.in_modiv).any() else "n/a",
            "assessment_parsed": f"{t[t.in_modiv].net_taxable.notna().mean():.1%}",
            "tax2025_match_$1": f"{has25.tax25_match.mean():.1%}" if len(has25) else "n/a",
            "full_2026_bills": int(t.tax26.notna().sum()),
            "median_2026_rate": round(t.implied_rate_26.median(), 4),
            "median_change_25_26": round(t.change_pct.median(), 2),
            "median_h2_vs_h1": round(t.h2_vs_h1_pct.median(), 2),
        })
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).to_string(index=False))

    bad = taxed[taxed.in_modiv & taxed.tax25.notna() & (taxed.last_year_tax > 0) & ~taxed.tax25_match]
    if len(bad):
        print(f"\n2025 mismatches ({len(bad)}), first 15:")
        print(bad[["pin", "property_class", "net_taxable", "net_value", "tax25", "last_year_tax"]].head(15).to_string(index=False))
    missing = m[~m.in_modiv]
    if len(missing):
        print(f"\nPortal accounts not in MOD-IV 2026 ({len(missing)}), first 10:")
        print(missing[["pin", "property_location", "property_class", "status"]].head(10).to_string(index=False))
    if args.out:
        m.drop(columns=[c for c in m.columns if c.endswith("_modiv")]).to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
