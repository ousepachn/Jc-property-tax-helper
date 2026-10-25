"""Load the county tax board's assessment records (taxrecords-nj.com) into the store.

  python pipeline/fetch_county_records.py --town jersey-city            # uses $DATABASE_URL, else the local file
  python pipeline/fetch_county_records.py --town jersey-city --from export.zip   # an export you downloaded

The NJ county tax boards' public records search can export a whole municipality as one CSV, so a
town costs two requests (search, then download). Beyond the state's MOD-IV list, the export has the
building's floor area, the last sale's SR-1A nonusable code and sales ratio, and four years of
assessments.

Three tables, all in the private store:
  parcels              building, lot, sale and location fields, one row per parcel record (public-
                       record facts; the only table a public page may be built from). A partly exempt
                       parcel (e.g. an abatement) has two records: record_type M (taxable) and X (exempt).
  parcel_assessments   land / building / exempt / total by tax-list year
  parcel_owners        owner name, mailing address, mortgage account and bank code, by year: private,
                       for analysis and for verifying owners; never exported to a public page
Each run replaces the town's rows with the latest export.
"""
import argparse
import csv
import io
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from portals.http import PoliteSession  # noqa: E402
from portals.models import make_pin, pin_part  # noqa: E402
from portals.registry import TOWNS  # noqa: E402
from store import connect, lock_down  # noqa: E402

BASE = "https://taxrecords-nj.com/pub"
COUNTY_USER = {"09": "ctb09"}   # Hudson; the search is per county tax board

SCHEMA = """
CREATE TABLE IF NOT EXISTS parcels (
  county_district TEXT, pin TEXT, record_type TEXT, block TEXT, lot TEXT, qualifier TEXT, property_location TEXT,
  property_class TEXT, sq_ft INTEGER, year_built INTEGER, building_class TEXT, building_desc TEXT,
  land_desc TEXT, acreage REAL, zone TEXT, map_page TEXT, additional_lots TEXT, account TEXT,
  prior_block TEXT, prior_lot TEXT, prior_qual TEXT, special_tax_codes TEXT, class4_code TEXT,
  epl_own TEXT, epl_use TEXT, epl_desc TEXT, epl_statute TEXT, epl_init TEXT, epl_further TEXT,
  epl_facility TEXT, taxes_1 REAL, taxes_2 REAL, taxes_3 REAL, taxes_4 REAL,
  sale_date TEXT, deed_book TEXT, deed_page TEXT, sale_price REAL, nu_code TEXT, sale_ratio REAL,
  type_use TEXT, latitude REAL, longitude REAL, neighborhood TEXT, vcs TEXT, style TEXT,
  record_updated TEXT, data_as_of TEXT, fetched_at TEXT,
  PRIMARY KEY (county_district, pin, record_type)
);
CREATE TABLE IF NOT EXISTS parcel_assessments (
  county_district TEXT, pin TEXT, record_type TEXT, year SMALLINT, land REAL, building REAL, exempt REAL,
  total REAL,
  PRIMARY KEY (county_district, pin, record_type, year)
);
CREATE TABLE IF NOT EXISTS parcel_owners (
  county_district TEXT, pin TEXT, record_type TEXT, year SMALLINT, owner_name TEXT, mailing_address TEXT,
  mailing_city_state_zip TEXT, mortgage_account TEXT, bank_code TEXT,
  PRIMARY KEY (county_district, pin, record_type, year)
);
"""
TABLES = ("parcels", "parcel_assessments", "parcel_owners")

# export columns, by position (the header repeats names: four Sp Tax Cd, four history blocks)
COL = {"district": 0, "block": 1, "lot": 2, "qual": 3, "location": 4, "class": 5, "owner": 6, "mail": 7,
       "mail_csz": 8, "sq_ft": 9, "year_built": 10, "building_class": 11, "prior_block": 12, "prior_lot": 13,
       "prior_qual": 14, "updated": 15, "zone": 16, "account": 17, "mortgage_account": 18, "bank_code": 19,
       "map_page": 24, "additional_lots": 25, "land_desc": 26, "building_desc": 27, "class4_code": 28,
       "acreage": 29, "epl_own": 30, "epl_use": 31, "epl_desc": 32, "epl_statute": 33, "epl_init": 34,
       "epl_further": 35, "epl_facility": 36, "sale_date": 41, "deed_book": 42, "deed_page": 43,
       "sale_price": 44, "nu_code": 45, "ratio": 46, "type_use": 47, "latitude": 84, "longitude": 85,
       "neighborhood": 86, "vcs": 87, "style_desc": 88, "style": 89, "join": 90}
SPECIAL_TAX = range(20, 24)
TAXES = range(37, 41)
HISTORY = [48 + 9 * k for k in range(4)]   # Year, Owner, Street, City/State/Zip, Land, Building, Exempt, Total, Assessed
EXPECTED_HEADER = {0: "Municipality", 9: "Sq. Ft.", 45: "NU Code", 48: "Year", 84: "Latitude"}


def num(s):
    try:
        v = float(str(s).replace(",", "").strip())
    except ValueError:
        return None
    return v


def positive(s):
    v = num(s)
    return v if v and v > 0 else None


def text(s):
    s = (s or "").strip()
    return s if s and s not in ("0", "000000") else None


def check_header(header):
    for i, name in EXPECTED_HEADER.items():
        if i >= len(header) or header[i].strip() != name:
            raise SystemExit(f"export layout changed: column {i} is {header[i] if i < len(header) else 'missing'!r}, "
                             f"expected {name!r}; update COL in fetch_county_records.py")


def parse_rows(rows, data_as_of, fetched_at):
    """Yield (parcel, [assessment], [owner]) dicts from export rows (header already removed)."""
    for r in rows:
        if len(r) < 90 or not r[COL["block"]].strip():
            continue
        g = lambda k: r[COL[k]].strip()
        cd = g("district")
        pin = make_pin(cd, pin_part(g("block")), pin_part(g("lot")), g("qual"))
        rt = g("join")[-1:] or "M"   # the join key ends in M (main, taxable) or X (exempt portion)
        year_built = positive(g("year_built"))
        lat, lon = num(g("latitude")), num(g("longitude"))
        parcel = {
            "county_district": cd, "pin": pin, "record_type": rt, "block": g("block"), "lot": g("lot"), "qualifier": g("qual") or None,
            "property_location": g("location"), "property_class": g("class"),
            "sq_ft": int(positive(g("sq_ft"))) if positive(g("sq_ft")) else None,
            "year_built": int(year_built) if year_built and 1700 < year_built < 2100 else None,
            "building_class": text(g("building_class")), "building_desc": text(g("building_desc")),
            "land_desc": text(g("land_desc")), "acreage": positive(g("acreage")), "zone": text(g("zone")),
            "map_page": text(g("map_page")), "additional_lots": text(g("additional_lots")), "account": text(g("account")),
            "prior_block": text(g("prior_block")), "prior_lot": text(g("prior_lot")), "prior_qual": text(g("prior_qual")),
            "special_tax_codes": " ".join(c for c in (r[i].strip() for i in SPECIAL_TAX) if c) or None,
            "class4_code": text(g("class4_code")),
            **{k: text(g(k)) for k in ("epl_own", "epl_use", "epl_desc", "epl_statute", "epl_init", "epl_further")},
            "epl_facility": text(g("epl_facility")),
            **{f"taxes_{n + 1}": num(r[i]) for n, i in enumerate(TAXES)},
            "sale_date": text(g("sale_date")), "deed_book": text(g("deed_book")), "deed_page": text(g("deed_page")),
            "sale_price": num(g("sale_price")), "nu_code": g("nu_code") or None, "sale_ratio": num(g("ratio")),
            "type_use": text(g("type_use")),
            "latitude": lat if lat else None, "longitude": lon if lon else None,
            "neighborhood": text(g("neighborhood")), "vcs": text(g("vcs")),
            "style": text(g("style_desc")) or text(g("style")),
            "record_updated": text(g("updated")), "data_as_of": data_as_of, "fetched_at": fetched_at,
        }
        assessments, owners = [], []
        for i in HISTORY:
            year = positive(r[i])
            if not year:
                continue
            assessments.append({"county_district": cd, "pin": pin, "record_type": rt, "year": int(year), "land": num(r[i + 4]),
                                "building": num(r[i + 5]), "exempt": num(r[i + 6]), "total": num(r[i + 7])})
            owners.append({"county_district": cd, "pin": pin, "record_type": rt, "year": int(year), "owner_name": text(r[i + 1]),
                           "mailing_address": text(r[i + 2]), "mailing_city_state_zip": text(r[i + 3]),
                           "mortgage_account": None, "bank_code": None})
        if owners:   # the current owner block carries the mailing address and mortgage fields
            cur = max(owners, key=lambda o: o["year"])
            cur.update(owner_name=text(g("owner")) or cur["owner_name"], mailing_address=text(g("mail")),
                       mailing_city_state_zip=text(g("mail_csz")), mortgage_account=text(g("mortgage_account")),
                       bank_code=text(g("bank_code")))
        yield parcel, assessments, owners


def read_export(zip_bytes):
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    rows = csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="latin-1"))
    header = next(rows)
    check_header(header)
    return rows


def download(cd, session):
    """Search the whole municipality with spreadsheet output, then fetch the zip it links to."""
    user = COUNTY_USER[cd[:2]]
    r = session.post(f"{BASE}/cgi/inf.cgi", data={
        "ms_user": user, "passwd": "", "srch_type": "1", "select_cc": f"{cd[:2]}01", "district": cd, "adv": "1",
        "out_type": "3", "ms_ln": "50", "p_loc": "", "owner": "", "block": "", "lot": "", "qual": ""}, timeout=600)
    link = re.search(r"download/[\w.-]+\.zip", r.text)
    found = re.search(r"([\d,]+) Records Found", r.text)
    as_of = re.search(r"Data as of (\d\d/\d\d/\d\d)", r.text)
    if not link:
        raise SystemExit(f"{cd}: the records search returned no download link")
    z = session.get(f"{BASE}/{link.group(0)}", timeout=600)
    as_of_iso = datetime.strptime(as_of.group(1), "%m/%d/%y").date().isoformat() if as_of else None
    return z.content, as_of_iso, int(found.group(1).replace(",", "")) if found else None


def insert(db, table, rows):
    if not rows:
        return
    cols = list(rows[0])
    db.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                   [tuple(r[c] for c in cols) for r in rows])


def load(db, cd, rows, data_as_of, fetched_at):
    parcels, assessments, owners = {}, [], {}
    for p, a, o in parse_rows(rows, data_as_of, fetched_at):
        parcels[(p["pin"], p["record_type"])] = p    # keep the last if a record repeats
        assessments.extend(a)
        for x in o:
            owners[(x["pin"], x["record_type"], x["year"])] = x
    assessments = list({(a["pin"], a["record_type"], a["year"]): a for a in assessments}.values())
    db.schema_lock()
    for t in TABLES:
        db.execute(f"DELETE FROM {t} WHERE county_district=?", (cd,))
    insert(db, "parcels", list(parcels.values()))
    insert(db, "parcel_assessments", assessments)
    insert(db, "parcel_owners", list(owners.values()))
    db.commit()
    return len(parcels), len(assessments), len(owners)


def open_db(target):
    db = connect(target)
    db.schema_lock()
    db.executescript(SCHEMA)
    lock_down(db, TABLES)
    db.commit()
    return db


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("DATABASE_URL") or "data/portal/bills.sqlite")
    ap.add_argument("--town", action="append", choices=TOWNS, required=True)
    ap.add_argument("--from", dest="source", help="load this export zip instead of downloading (one town only)")
    args = ap.parse_args(argv)
    if args.source and len(args.town) > 1:
        ap.error("--from loads one town")
    db = open_db(args.db)
    session = PoliteSession(min_interval=5.0, timeout=600)
    for town in args.town:
        cd = TOWNS[town]["county_district"]
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if args.source:
            content, as_of, expected = Path(args.source).read_bytes(), None, None
        else:
            content, as_of, expected = download(cd, session)
        n_p, n_a, n_o = load(db, cd, read_export(content), as_of, fetched_at)
        print(f"{TOWNS[town]['name']}: {n_p:,} parcel records, {n_a:,} assessment rows, {n_o:,} owner rows"
              + (f" (search reported {expected:,} records)" if expected else "") + (f", data as of {as_of}" if as_of else ""))


if __name__ == "__main__":
    main()
