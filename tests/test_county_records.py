"""County tax board export loader, on a synthetic export (no real owner data in the repo)."""
import csv
import io
import os
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import fetch_county_records as fcr  # noqa: E402
import store  # noqa: E402

HEADER = ["Municipality", "Block", "Lot", "Qual", "Property Location", "Property Class", "Owner's Name",
          "Owner's Mailing Address", "City/State/Zip", "Sq. Ft.", "Yr. Built", "Building Class", "Prior Block",
          "Prior Lot", "Prior Qual", "Updated", "Zone", "Account", "Mortgage Account", "Bank Code",
          "Sp Tax Cd", "Sp Tax Cd", "Sp Tax Cd", "Sp Tax Cd", "Map Page", "Additional Lots", "Land Desc",
          "Building Desc", "Class 4 Code", "Acreage", "EPL Own", "EPL Use", "EPL Desc", "EPL Statute", "EPL Init",
          "EPL Further", "EPL Facility Name", "Taxes 1", "Taxes 2", "Taxes 3", "Taxes 4", "Sale Date", "Deed Book",
          "Deed Page", "Sale Price", "NU Code", "Ratio", "Type/Use"]
for _ in range(4):
    HEADER += ["Year", "Owner", "Street", "City/State/Zip", "Land Assmnt", "Building Assmnt", "Exempt",
               "Total Assmnt", "Assessed"]
HEADER += ["Latitude", "Longitude", "Neigh", "VCS", "StyDesc", "Style", "Join", ""]


def row(block, lot, qual, cls, sq_ft, total, rec="M", owner="SAMPLE, OWNER", sale=("2025-03-01", "500000", "0")):
    r = [""] * len(HEADER)
    vals = {0: "0906", 1: block, 2: lot, 3: qual, 4: "1 SAMPLE ST.", 5: cls, 6: owner, 7: "1 MAIL ST.",
            8: "JERSEY CITY, N.J. 07306", 9: sq_ft, 10: "1900", 11: "17.4", 17: "00012345", 18: "MTG1", 19: "154",
            26: "25X100", 27: "2S-F-D-2U", 29: "0.0574", 37: "9000", 38: "10000", 39: "0", 40: "0",
            41: sale[0], 44: sale[1], 45: sale[2], 46: "90", 84: "0", 85: "0",
            90: f"{block:>5}{lot:>9}{qual:>7}{rec}"}
    for k, (year, t) in enumerate(((2026, total), (2025, total), (2024, total * 0.9), (2023, total * 0.9))):
        b = 48 + 9 * k
        vals.update({b: str(year), b + 1: owner if k < 2 else "PRIOR, OWNER", b + 2: "1 SAMPLE ST.",
                     b + 3: "JERSEY CITY", b + 4: "200000", b + 5: str(t - 200000), b + 6: "0", b + 7: str(t),
                     b + 8: str(t)})
    for i, v in vals.items():
        r[i] = v
    return r


def export_zip(rows):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow(HEADER)
    w.writerows(rows)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("0906ctb09000000.csv", buf.getvalue().encode("latin-1"))
    return out.getvalue()


SAMPLE = [
    row("5803", "38", "", "2", "3700", 950000),
    row("39.01", "9", "C0602", "2", "900", 330800),
    row("5003", "1", "C0001", "1", "833", 43900, rec="M"),          # abated condo: taxable part ...
    row("5003", "1", "C0001", "15F", "833", 378100, rec="X"),       # ... and its exempt part
    row("101", "1.01", "HM", "4B", "0", 1000, sale=("2049-11-01", "1", "3")),
]


def load_sample(target, rows=SAMPLE):
    db = fcr.open_db(target)
    n = fcr.load(db, "0906", fcr.read_export(export_zip(rows)), "2026-10-01", "2026-10-25T00:00:00+00:00")
    return db, n


def test_parse_and_load_sqlite(tmp_path):
    db, (n_p, n_a, n_o) = load_sample(tmp_path / "t.sqlite")
    assert (n_p, n_a, n_o) == (5, 20, 20)
    c = sqlite3.connect(tmp_path / "t.sqlite")
    p = dict(zip([d[0] for d in c.execute("SELECT * FROM parcels WHERE pin='0906_5803_38'").description],
                 c.execute("SELECT * FROM parcels WHERE pin='0906_5803_38'").fetchone()))
    assert p["sq_ft"] == 3700 and p["year_built"] == 1900 and p["building_desc"] == "2S-F-D-2U"
    assert p["sale_price"] == 500000 and p["nu_code"] == "0" and p["record_type"] == "M"
    assert p["latitude"] is None                                  # 0 means no position
    assert c.execute("SELECT record_type, property_class FROM parcels WHERE pin='0906_5003_1_C0001' "
                     "ORDER BY record_type").fetchall() == [("M", "1"), ("X", "15F")]
    assert c.execute("SELECT pin FROM parcels WHERE block='39.01'").fetchone()[0] == "0906_39.01_9_C0602"
    assert c.execute("SELECT year, total FROM parcel_assessments WHERE pin='0906_5803_38' ORDER BY year").fetchall() \
        == [(2023, 855000.0), (2024, 855000.0), (2025, 950000.0), (2026, 950000.0)]
    # private fields live only in parcel_owners, and the current year carries mailing + mortgage
    assert "owner_name" not in [d[0] for d in c.execute("SELECT * FROM parcels").description]
    assert c.execute("SELECT owner_name, mortgage_account FROM parcel_owners WHERE pin='0906_5803_38' AND year=2026"
                     ).fetchone() == ("SAMPLE, OWNER", "MTG1")
    assert c.execute("SELECT owner_name, mortgage_account FROM parcel_owners WHERE pin='0906_5803_38' AND year=2023"
                     ).fetchone() == ("PRIOR, OWNER", None)


def test_reload_replaces_the_town(tmp_path):
    load_sample(tmp_path / "t.sqlite")
    db, n = load_sample(tmp_path / "t.sqlite", SAMPLE[:2])
    assert n[0] == 2
    assert sqlite3.connect(tmp_path / "t.sqlite").execute("SELECT COUNT(*) FROM parcel_owners").fetchone()[0] == 8


def test_layout_change_is_refused():
    bad = export_zip([])
    z = zipfile.ZipFile(io.BytesIO(bad))
    text = z.read(z.namelist()[0]).decode("latin-1").replace("Sq. Ft.", "Square Feet")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zz:
        zz.writestr("x.csv", text)
    with pytest.raises(SystemExit, match="layout changed"):
        fcr.read_export(out.getvalue())


def test_download_parses_search_page():
    class Resp:
        def __init__(self, text="", content=b""):
            self.text, self.content = text, content

    class Session:
        def __init__(self):
            self.calls = []

        def post(self, url, data=None, timeout=None):
            self.calls.append(("POST", url, data))
            return Resp("64813 Records Found for DownloadData as of 10/01/26 <a href=../download/0906ctb09123.zip>")

        def get(self, url, timeout=None):
            self.calls.append(("GET", url))
            return Resp(content=b"zip")

    s = Session()
    assert fcr.download("0906", s) == (b"zip", "2026-10-01", 64813)
    assert s.calls[0][2]["district"] == "0906" and s.calls[0][2]["out_type"] == "3"
    assert s.calls[1][1] == "https://taxrecords-nj.com/pub/download/0906ctb09123.zip"


PG = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.skipif(not PG, reason="set TEST_DATABASE_URL to run Postgres tests")
def test_load_postgres_and_lock_down():
    import psycopg
    with psycopg.connect(PG, autocommit=True) as c:
        c.execute(f"DROP SCHEMA IF EXISTS {store.PG_SCHEMA} CASCADE")
    load_sample(PG)
    load_sample(PG)                                               # reload is clean
    with psycopg.connect(PG, autocommit=True) as c:
        c.execute(f"SET search_path TO {store.PG_SCHEMA}")
        assert c.execute("SELECT COUNT(*), COUNT(sq_ft) FROM parcels").fetchone() == (5, 4)
        assert c.execute("SELECT COUNT(*) FROM parcel_owners").fetchone()[0] == 20
        rls = dict(c.execute("""SELECT relname, relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                                WHERE n.nspname = %s AND c.relkind = 'r' AND relname LIKE 'parcel%%'""", (store.PG_SCHEMA,)).fetchall())
        assert rls == {"parcels": True, "parcel_assessments": True, "parcel_owners": True}
