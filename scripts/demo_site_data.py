"""Made-up data to try the website locally, no database or secrets needed.

  python scripts/demo_site_data.py            # writes site/data (what `npm run dev` reads without SITE_DATABASE_URL)
  cd site && npm install && npm run dev       # then open http://localhost:3000

1,000 houses on a grid of streets, a 120-unit condo tower at 77 Hudson St, an abated tower at 1 River Dr,
a building whose abatement ended at 20 Bay St, eight years of quarterly bills and a few permits. Every address, value and permit is invented.
"""
import random, sys, tempfile
from pathlib import Path
R = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(R / "pipeline"), str(R / "tests")]
import extract_bills, fetch_county_records as fcr, fetch_permits as F
from test_county_records import export_zip, row
from test_abatements import history
out = Path(tempfile.mkdtemp(prefix="demo-site-"))
db_path = out / "demo.sqlite"; db_path.unlink(missing_ok=True)
random.seed(4)
streets = ["GROVE ST.", "PAVONIA AVE.", "SECOND ST.".replace("SECOND", "2ND"), "MONTGOMERY ST.", "JERSEY AVE.", "BRUNSWICK ST.", "NEWARK AVE.", "WAYNE ST."]
rows, pos, props = [], [], []
LAT0, LON0 = 40.715, -74.055
for b in range(40):
    for l in range(1, 26):
        block, lot = str(10000 + b * 100), str(l)
        st = streets[b % len(streets)]
        addr = f"{100 + l * 2 + (b // 8) * 100} {st}"
        sq = random.choice([1400, 1600, 1800, 2000, 2400])
        total = random.randint(350, 900) * 1000
        r = row(block, lot, "", "2", str(sq), total, sale=(f"2026-0{random.randint(1,9)}-01", str(int(total * random.uniform(1.2, 1.8))), "0"))
        r[4] = addr; r[10] = str(random.choice([1890, 1905, 1925, 1990, 2005]))
        rows.append(r)
        lat, lon = LAT0 + b * 0.0011 + random.uniform(-0.0002, 0.0002), LON0 + l * 0.0009 + random.uniform(-0.0002, 0.0002)
        pos.append((f"0906_{block}_{lot}", lat, lon, 2)); props.append(f"0906_{block}_{lot}")
# condo tower, 77 HUDSON ST.: fully taxed, value rising by floor, a few units assessed high
for fl in range(2, 32):
    for u in ("01", "02", "03", "04"):
        q = f"C{fl:02d}{u}"
        sq = {"01": 700, "02": 850, "03": 1100, "04": 850}[u]
        value = int(sq * (520 + fl * 6) * random.uniform(0.97, 1.03) * (1.25 if (fl, u) in ((12, "01"), (20, "03")) else 1))
        r = row("14502", "1", q, "2", str(sq), value)
        r[4] = "77 HUDSON ST."; r[27] = "30S-CONDO"; r[10] = "2008"
        rows.append(r); props.append(f"0906_14502_1_{q}")
pos.append(("0906_14502_1", 40.7165, -74.0335, 120))
# abated tower, 1 RIVER DR.: land taxed, building exempt under the long-term law until 2031
for fl in range(2, 22):
    for u in ("01", "02"):
        q = f"C{fl:02d}{u}"
        r = history(row("14601", "1", q, "2", "900", 0), {y: (40000, 0) for y in (2023, 2024, 2025, 2026)})
        r[4] = "1 RIVER DR."; r[10] = "2011"
        x = history(row("14601", "1", q, "15F", "900", 0, rec="X"), {y: (0, 420000 + fl * 4000) for y in (2023, 2024, 2025, 2026)})
        x[4] = "1 RIVER DR."; x[33], x[34], x[35] = "40A:20-1", "070111", "063031"
        rows += [r, x]; props.append(f"0906_14601_1_{q}")
pos.append(("0906_14601_1", 40.7180, -74.0320, 40))
# 20 BAY ST.: its five-year abatement ended in 2026, so the building came onto the roll
for u in range(1, 9):
    q = f"C00{u}0"
    r = history(row("14701", "3", q, "2", "800", 0), {2023: (38000, 0), 2024: (38000, 0), 2025: (38000, 0), 2026: (38000, 480000)})
    r[4] = "20 BAY ST."; r[10] = "2020"
    rows.append(r); props.append(f"0906_14701_3_{q}")
pos.append(("0906_14701_3", 40.7150, -74.0340, 8))
db = fcr.open_db(db_path)
fcr.load(db, "0906", fcr.read_export(export_zip(rows)), "2026-10-01", "2026-10-25T00:00:00+00:00")
with open(out / "parcels.csv", "w") as fh:
    fh.write("PAMS_PIN,LAT,LON,DWELL\n")
    for p, la, lo, d in pos: fh.write(f"{p},{la},{lo},{d}\n")
db = extract_bills.connect(db_path)
rates = {2019: 1.540, 2020: 1.610, 2021: 1.604, 2022: 2.118, 2023: 2.247, 2024: 2.233, 2025: 2.335, 2026: 2.657}
bills = []
for i, pin in enumerate(props):
    db.execute("INSERT INTO accounts (county_district, account_id, pin, status, fetched_at) VALUES (?,?,?,?,?)", ("0906", str(i), pin, "done", "2026-10-01"))
    a = random.randint(300, 800) * 1000; drift = random.uniform(-0.03, 0.06)
    tax = {y: a * (1 + drift) ** (y - 2019) * rates[y] / 100 for y in rates}
    for y in rates:
        half_prev = tax.get(y - 1, tax[y]) / 2
        for q in (1, 2): bills.append(("0906", str(i), y, q, f"{y}-0{q*3-1}-01", "tax", "property_tax", half_prev / 2, 0.0, 0.0))
        for q in (3, 4): bills.append(("0906", str(i), y, q, f"{y}-{q*3-1:02d}-01", "tax", "property_tax", (tax[y] - half_prev) / 2, 0.0, 0.0))
    if i % 37 == 0: bills.append(("0906", str(i), 2024, 4, "2024-11-01", "added", "property_tax", 1800.0, 0.0, 0.0))
db.executemany(f"INSERT INTO bills ({', '.join(extract_bills.BILL_COLUMNS)}) VALUES (?,?,?,?,?,?,?,?,?,?)", bills)
db.commit()
db = F.open_db(db_path)
def permit(no, pin, ctype, issued, status="Issued", final=None, desc="work"):
    return {"permit_no": no, "case_id": no, "pin": pin, "address": "x", "case_type": ctype, "work_class": "", "status": status,
            "apply_date": issued, "issue_date": issued, "final_date": final, "expire_date": None, "description": desc}
ps = [
    permit("CNST-26-1001", "0906_10000_1", "Construction Permit Application - Addition", "2026-04-02", desc="Rear two-story addition with new bathroom"),
    permit("CNST-24-0412", "0906_10000_1", "Construction Permit Application - Alteration/Renovation", "2024-03-11", "Complete", "2024-08-30", "Replace boiler in kind"),
    permit("CNST-25-2210", "0906_10000_2", "Construction Permit Application - Alteration/Renovation", "2025-02-14", "Complete", "2025-09-01", "Finish basement, add half bath"),
    permit("CNST-26-3001", "0906_14502_1", "Construction Permit Application - Alteration/Renovation", "2026-06-01", desc="Lobby renovation and elevator modernization"),
    permit("CNST-26-3002", "0906_14502_1_C1201", "Construction Permit Application - Alteration/Renovation", "2026-08-11", desc="Kitchen and bath renovation"),
]
F.upsert(db, ps, "2026-10-27"); db.commit()
import build_site as B
site, meta = B.build(B.connect(str(db_path)), "0906", B.load_positions(out / "parcels.csv"))
B.write_json(site, meta, R / "site" / "data")
print(f"{len(site):,} made-up properties written to site/data. Try: 102 Grove St, 77 Hudson St 1201, 1 River Dr, 20 Bay St")
