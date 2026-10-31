"""Abatements, condo-building comparisons and citywide totals (pipeline/abatements.py, build_site.py)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import abatements as A  # noqa: E402
import build_site as B  # noqa: E402
import fetch_county_records as fcr  # noqa: E402
from test_county_records import export_zip, row  # noqa: E402

LAT, LON = 40.7300, -74.0600


def history(r, by_year):
    """Set a row's assessment history: {year: (land, building)}."""
    for k, year in enumerate((2026, 2025, 2024, 2023)):
        b = 48 + 9 * k
        land, bld = by_year[year]
        r[b + 4], r[b + 5], r[b + 7], r[b + 8] = str(land), str(bld), str(land + bld), str(land + bld)
    return r


def test_laws_and_dates():
    assert A.law_of("40A:20-1") == "long_term" and A.law_of("40A:201") == "long_term"
    assert A.law_of("40A:21-5") == "five_year" and A.law_of("46A:21-5") == "five_year"
    assert A.law_of("55:14K-1") == "affordable" and A.law_of("54:4-3.6") is None
    assert A.mmddyy("062409") == "2009-06-24" and A.mmddyy("123199") == "1999-12-31" and A.mmddyy("") is None
    assert A.active("54:4-3.6", None, None, 1000, full=True) is None              # a church, not an abatement
    a = A.active("40A:20-1", "062409", "062329", 490100, full=False)
    assert (a["law"], a["since"], a["until"], a["exempt_value"]) == ("long_term", "2009-06-24", "2029-06-23", 490100)


def test_ended_year():
    h = {2023: (40900, 0), 2024: (40900, 0), 2025: (40900, 0), 2026: (40900, 540200)}
    assert A.ended_year(h, 2005) == 2026
    assert A.ended_year(h, 2025) is None                                   # new construction, not an abatement
    assert A.ended_year({2025: (100, 50), 2026: (100, 60)}, 1990) is None


def test_buildings_flag_units_above_their_floor():
    units = [{"pin": f"p{f}{u}", "unit": f"C{f:02d}0{u}", "sq_ft": 800, "value": 400000 + f * 8000, "abated": False}
             for f in range(2, 12) for u in (1, 2)]
    units[0]["value"] *= 1.25                                              # one unit assessed 25% above its floor
    out = A.buildings(units)
    assert A.floor_of("C1201") == 12 and A.floor_of("C0310") == 3 and A.floor_of("C003L") is None and A.floor_of("C0010") is None
    assert out["p21"]["above"] and out["p21"]["vs_floor"] > 0.15
    assert not out["p22"]["above"] and abs(out["p22"]["vs_floor"]) < 0.02
    assert len(out["p22"]["list"]) == A.SHOW_UNITS and out["p22"]["list"][0]["floor"] == 2
    assert A.buildings(units[:2]) == {}


def test_city_stats():
    rows = [{"class": "2", "value": 300, "abatement": None, "ended": None, "unit": False, "lot": "a"},
            {"class": "4A", "value": 700, "abatement": None, "ended": 2026, "unit": False, "lot": "b"},
            {"class": "2", "value": 50, "unit": True, "lot": "c", "ended": None,
             "abatement": A.active("40A:20-1", "010110", "123127", 950, full=False)},
            {"class": "15C", "value": 5000, "abatement": None, "ended": None, "unit": False, "lot": "d"}]
    s = A.city_stats(rows, 2.657, date(2026, 10, 27))
    assert s["taxable_value"] == 1050 and s["exempt_value"] == 5000
    assert s["by_class"][0] == {"label": "Homes and condos", "value": 350, "share": round(350 / 1050, 4)}
    ab = s["abatement"]
    assert (ab["properties"], ab["units"], ab["value"], ab["ending_soon"], ab["ended_recently"]) == (1, 1, 950, 1, 1)


def make_store(tmp_path, target=None):
    """The synthetic county records; in a SQLite file, or in Postgres when target is a URL."""
    rows = []
    for i in range(1, 13):                                  # 12 ordinary 2-family houses, as in test_build_site
        rows.append(row("100", str(i), "", "2", str(2000 + 10 * i), 500000 + 1000 * i,
                        sale=("2026-02-01", str(900000 + 5000 * i), "0")))
    for f in range(2, 8):                                   # an abated condo tower: land taxed, building exempt
        for u in (1, 2):
            q = f"C{f:02d}0{u}"
            # the taxable land share is filed as class 1 (vacant land), as on the real roll
            rows.append(history(row("300", "1", q, "1", "800", 45000), {y: (45000, 0) for y in (2023, 2024, 2025, 2026)}))
            x = history(row("300", "1", q, "15F", "800", 490000 + f * 5000, rec="X"),
                        {y: (0, 490000 + f * 5000) for y in (2023, 2024, 2025, 2026)})
            x[33], x[34], x[35] = "40A:20-1", "062409", "062329"
            rows.append(x)
    for u in (1, 2, 3):                                     # a condo building whose abatement ended in 2026
        r = row("400", "2", f"C00{u}0", "2", "750", 0)
        r[10] = "2005"
        rows.append(history(r, {2023: (40900, 0), 2024: (40900, 0), 2025: (40900, 0), 2026: (40900, 540200)}))
    path = target or tmp_path / "t.sqlite"
    db = fcr.open_db(path)
    fcr.load(db, "0906", fcr.read_export(export_zip(rows)), "2026-10-01", "2026-10-25T00:00:00+00:00")
    parcels = tmp_path / "parcels.csv"
    with open(parcels, "w") as fh:
        fh.write("PAMS_PIN,LAT,LON,DWELL\n")
        for i in range(1, 13):
            fh.write(f"0906_100_{i},{LAT + i * 0.0003},{LON},2\n")
        fh.write(f"0906_300_1,{LAT + 0.001},{LON + 0.001},12\n0906_400_2,{LAT + 0.002},{LON},3\n")
    return path, parcels


def test_build_abated_and_ended(tmp_path):
    path, parcels = make_store(tmp_path)
    out, meta = B.build(B.connect(path), "0906", B.load_positions(parcels), today=date(2026, 10, 27))
    tower = out["0906_300_1_C0201"]
    assert tower["kind"] == "condo" and tower["abatement"]["law"] == "long_term"
    assert tower["abatement"]["until"] == "2029-06-23" and tower["abatement"]["exempt_value"] == 500000
    assert tower["compare"]["count"] == 0 and tower["appeal"]["score"] == "not_applicable"
    assert tower["change"] is None and tower["change_q4"] is None
    bc = tower["building_compare"]
    assert bc["units"] == 12 and bc["abated_units"] == 12 and bc["value"] == 45000 + 500000
    ended = out["0906_400_2_C0010"]
    assert ended["abatement"] == {"status": "ended", "year": 2026} and ended["change"] is None
    house = out["0906_100_1"]
    pool = {n["pin"] for n in house["compare"]["list"]}
    assert not any(p.startswith(("0906_300", "0906_400")) for p in pool)       # abated / ended never neighbors
    assert B.summary_row(tower)[-1] == 1 and B.summary_row(ended)[-1] == 4 and B.summary_row(house)[-1] == 0
    ab = meta["city"]["abatement"]
    assert (ab["properties"], ab["units"], ab["buildings"], ab["ended_recently"]) == (12, 12, 1, 3)
    assert meta["city"]["taxable_value"] > 0


def test_abatement_charges_are_categorized():
    from portals.models import categorize
    assert categorize("ab-95_van_dam") == "abatement_charge"
    assert categorize("c138-admin_fee") == "abatement_charge" and categorize("c138-county_chg") == "abatement_charge"
    assert categorize("prorated_abatement") == "abatement_charge"
    assert categorize("tax") == "property_tax" and categorize("water") == "other"
    assert categorize("cancel_hudson_cty_bd_adjustment") == "appeal_adjustment"


def pg_target():
    import os
    import pytest
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to run Postgres tests")
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS portal CASCADE")
    return url


def test_build_counts_abatement_charges_as_paid_postgres(tmp_path):
    test_build_counts_abatement_charges_as_paid(tmp_path, pg_target())


def test_build_counts_abatement_charges_as_paid(tmp_path, target=None):
    """300 Communipaw-style: land tax plus the abatement charge until 2025, then full tax."""
    import extract_bills
    path, parcels = make_store(tmp_path, target)
    db = extract_bills.connect(path)
    pin = "0906_400_2_C0010"
    db.execute("INSERT INTO accounts (county_district, account_id, pin, status, fetched_at) VALUES (?,?,?,?,?)",
               ("0906", "1", pin, "done", "2026-10-01"))
    bills = []
    for y in range(2019, 2027):
        land_tax = 700 + 40 * (y - 2019)
        for q in (1, 2, 3, 4):
            bills.append((y, q, "tax", land_tax / 4 if y < 2026 else 19000 / 4))
            if y < 2025:
                bills += [(y, q, "ab-95_van_dam", 2000.0 + 100 * (y - 2019)), (y, q, "c138-county_chg", 110.0)]
    db.executemany(f"INSERT INTO bills ({', '.join(extract_bills.BILL_COLUMNS)}) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   [("0906", "1", y, q, f"{y}-0{q}-01", k, "other" if k != "tax" else "property_tax", a, 0.0, 0.0)
                    for y, q, k, a in bills])          # stored as 'other', as bills fetched before this change are
    db.commit()
    out, meta = B.build(B.connect(path), "0906", B.load_positions(parcels), today=date(2026, 10, 27))
    r = out[pin]
    assert r["abatement_charges"]["2020"] == 4 * (2100 + 110)
    assert r["tax"]["2020"] == 740 + 4 * (2100 + 110)                  # land tax plus what was paid instead
    assert r["change"] is not None and r["change_5y"] is not None       # real payments: comparable over time
    assert r["abatement"] == {"status": "ended", "year": 2026}
    house = out["0906_100_1"]
    assert not any(n["pin"] == pin for n in house["compare"]["list"])  # still kept out of other properties' pools


def test_project_named_charges_count_on_abated_accounts():
    # real labels from Jersey City bills: the charge is often named after the project
    for kind in ("lhn-_gulls_cove", "700_grove_st", "rialto-capitol", "new_liberty", "true_up_adjustment"):
        assert B.abatement_category(kind) == "abatement_charge", kind
    for kind in ("water", "sewer", "sid_exchange_pl", "bad_check_fee_adjustment", "nsf_chk_reversal_adjustment",
                 "transfer_to/from_qtr_adjustment", "payment_adjustment", "billing_adjustment"):
        assert B.abatement_category(kind) == "other", kind
    assert B.abatement_category("billing_adjustment", fully_abated=True) == "abatement_charge"
    assert B.abatement_category("tax") == "property_tax"


def test_project_named_charge_and_new_building(tmp_path):
    import extract_bills
    path, parcels = make_store(tmp_path)
    db = extract_bills.connect(path)
    rows = []
    for acct, pin, lines in (
        ("1", "0906_400_2_C0010", [("tax", 200.0), ("c138-county_chg", 100.0), ("lhn-_gulls_cove", 4000.0),
                                   ("water", 300.0)]),
        ("2", "0906_400_2_C0020", [("tax", 200.0)]),      # never a charge: building added, not an abatement ending
    ):
        db.execute("INSERT INTO accounts (county_district, account_id, pin, status, fetched_at) VALUES (?,?,?,?,?)",
                   ("0906", acct, pin, "done", "2026-10-01"))
        for y in range(2019, 2026):
            rows += [("0906", acct, y, 1, f"{y}-02-01", k, "other", a, 0.0, 0.0) for k, a in lines]
    db.executemany(f"INSERT INTO bills ({', '.join(extract_bills.BILL_COLUMNS)}) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    out, meta = B.build(B.connect(path), "0906", B.load_positions(parcels), today=date(2026, 10, 27))
    a = out["0906_400_2_C0010"]
    assert a["abatement_charges"]["2020"] == 4100 and a["tax"]["2020"] == 4300   # water left out
    assert a["abatement"] == {"status": "ended", "year": 2026}
    b = out["0906_400_2_C0020"]
    assert b["abatement"] is None and b["abatement_charges"] == {}


def test_main_writes_on_a_fresh_connection_postgres(tmp_path, monkeypatch):
    """Neon suspends an idle database mid-build and drops the connection (AdminShutdown)."""
    import psycopg
    url = pg_target()
    path, parcels = make_store(tmp_path, url)
    real_build = B.build

    def build_then_drop(db, cd, positions, today=None):
        out = real_build(db, cd, positions, today)
        with psycopg.connect(url, autocommit=True) as c:                # what Neon's suspend does
            c.execute("SELECT pg_terminate_backend(%s)", (db.conn.info.backend_pid,))
        return out

    monkeypatch.setattr(B, "build", build_then_drop)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS site CASCADE")
    B.main(["--db", url, "--parcels", str(parcels)])
    with psycopg.connect(url, autocommit=True) as c:
        assert c.execute("SELECT COUNT(*) FROM site.properties").fetchone()[0] == 27
