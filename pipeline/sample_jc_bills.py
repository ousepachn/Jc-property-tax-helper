"""Pull actual billed taxes for a stratified sample of Jersey City parcels from the
city's public Property Tax Inquiry (HLS Systems) to check how current/accurate the
state MOD-IV data is.

Polite by design: one request at a time with a delay, small sample. Owner names and
mailing addresses returned by the API are dropped and never written to disk.

Usage: python pipeline/sample_jc_bills.py data/interim/modiv_hudson_2026.csv data/interim/jc_bill_sample.csv
"""
import csv
import json
import sys
import time

import pandas as pd
import requests

from modiv import norm_block_lot

BASE = "https://apps.hlssystems.com/JerseyCity/PropertyTaxInquiry"
DELAY_S = 1.5
SEED = 20261017

# (label, filter, n)
STRATA = [
    ("residential_1_4_family", lambda d: (d.property_class == "2") & ~d.qualifier.str.startswith("C"), 40),
    ("residential_condo", lambda d: (d.property_class == "2") & d.qualifier.str.startswith("C"), 20),
    ("commercial_apartment", lambda d: d.property_class.isin(["4A", "4C"]), 15),
    ("abated_long_term_40A20", lambda d: d.exempt_statute.str.startswith("40A:20"), 10),
    ("abated_5yr_40A21", lambda d: d.exempt_statute.str.startswith("40A:21"), 10),
    ("vacant_land", lambda d: d.property_class == "1", 5),
]


def find_account(session, block, lot, qual):
    for page in range(1, 30):
        r = session.get(
            f"{BASE}/GetAccounts",
            params={"page": page, "searchType": "BLQ", "searchField": f"{block} {lot}"},
            timeout=60,
        )
        time.sleep(DELAY_S)
        accts = r.json().get("accounts", [])
        for a in accts:
            if (a["Block"].strip(), a["Lot"].strip(), (a["Qualifier"] or "").strip()) == (block, lot, qual):
                return a["AccountNumber"]
        if len(accts) < 10:
            return None
    return None


def get_details(session, account):
    r = session.get(
        f"{BASE}/GetAccountDetails",
        params={"accountNumber": account, "interestThruDate": time.strftime("%a %b %d %Y")},
        timeout=60,
    )
    time.sleep(DELAY_S)
    return r.json()["accountInquiryVM"]


def main(modiv_csv, out_csv):
    d = pd.read_csv(modiv_csv, dtype=str, low_memory=False).fillna("")
    d = d[(d.county_district == "0906") & (d.record_id == "20")]
    picks = []
    for label, flt, n in STRATA:
        pool = d[flt(d)]
        picks.append(pool.sample(min(n, len(pool)), random_state=SEED).assign(stratum=label))
    sample = pd.concat(picks)

    session = requests.Session()
    session.get("https://apps.hlssystems.com/JerseyCity/PropertyTaxInquiry", timeout=60)
    cols = [
        "stratum", "pin", "block", "lot", "qualifier", "property_class", "property_location",
        "exempt_statute", "modiv_net_value", "modiv_last_year_tax", "found", "city_net_taxable",
        "billed_2025", "billed_2026", "q1_2026", "q2_2026", "q3_2026", "q4_2026",
        "q1_2027", "daniels_law",
    ]
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for i, (_, p) in enumerate(sample.iterrows(), 1):
            block, lot, qual = norm_block_lot(p.block), norm_block_lot(p.lot), p.qualifier.strip()
            row = {
                "stratum": p.stratum, "pin": p.pin, "block": block, "lot": lot, "qualifier": qual,
                "property_class": p.property_class, "property_location": p.property_location,
                "exempt_statute": p.exempt_statute, "modiv_net_value": p.net_value,
                "modiv_last_year_tax": p.last_year_tax, "found": False,
            }
            try:
                acct = find_account(session, block, lot, qual)
                if acct:
                    vm = get_details(session, acct)
                    yearly = {y["Year"]: y for y in vm.get("YearlySummaries") or []}
                    q = {}
                    for t in vm.get("Details") or []:
                        if t["Description"].strip() == "Taxes Bill":
                            key = (t["TaxYear"], t["Quarter"])
                            q[key] = q.get(key, 0) + t["Billed"]
                    row.update(
                        found=True,
                        city_net_taxable=vm.get("NetTaxable"),
                        billed_2025=yearly.get(2025, {}).get("NetBilled"),
                        billed_2026=yearly.get(2026, {}).get("NetBilled"),
                        q1_2026=q.get((2026, 1)), q2_2026=q.get((2026, 2)),
                        q3_2026=q.get((2026, 3)), q4_2026=q.get((2026, 4)),
                        q1_2027=q.get((2027, 1)), daniels_law=vm.get("DanielsLaw"),
                    )
            except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
                print(f"  error on {p.pin}: {e}", flush=True)
            w.writerow(row)
            fh.flush()
            print(f"{i}/{len(sample)} {p.pin} found={row['found']}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
