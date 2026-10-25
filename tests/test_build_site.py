"""Site data build, on a synthetic store: tax history, comparison, appeal screen, no private fields."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_site as B  # noqa: E402
import extract_bills  # noqa: E402
from test_county_records import export_zip, row  # noqa: E402

import fetch_county_records as fcr  # noqa: E402

LAT, LON = 40.7300, -74.0600


def make_store(tmp_path, with_bills=False):
    rows = [row("100", str(i), "", "2", str(2000 + 10 * i), 500000 + 1000 * i,
                sale=("2026-02-01", str(900000 + 5000 * i), "0")) for i in range(1, 13)]
    rows.append(row("200", "1", "", "4A", "5000", 2000000))                          # commercial: not compared
    path = tmp_path / "t.sqlite"
    db = fcr.open_db(path)
    fcr.load(db, "0906", fcr.read_export(export_zip(rows)), "2026-10-01", "2026-10-25T00:00:00+00:00")
    # the synthetic building code says 2 units, so these are 2-family houses
    parcels = tmp_path / "parcels.csv"
    with open(parcels, "w") as fh:
        fh.write("PAMS_PIN,LAT,LON,DWELL\n")
        for i in range(1, 13):
            fh.write(f"0906_100_{i},{LAT + i * 0.0003},{LON},2\n")
        fh.write(f"0906_200_1,{LAT},{LON},0\n")
    if with_bills:
        db = extract_bills.connect(path)
        for i in range(1, 13):
            db.execute("INSERT INTO accounts (county_district, account_id, pin, status, fetched_at) VALUES (?,?,?,?,?)",
                       ("0906", str(i), f"0906_100_{i}", "done", "2026-10-01"))
            bills = [(y, q, "tax", "property_tax", 2500.0 * (1 + 0.05 * (y - 2019))) for y in range(2019, 2027)
                     for q in (1, 2, 3, 4)]
            if i == 1:
                bills.append((2024, 2, "added", "property_tax", 900.0))          # renovation
            if i == 2:
                bills.append((2023, 1, "cancel_hudson_cty_bd_adjustment", "appeal_adjustment", -1000.0))
            db.executemany(f"INSERT INTO bills ({', '.join(extract_bills.BILL_COLUMNS)}) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           [("0906", str(i), y, q, f"{y}-0{q}-01", k, c, a, 0.0, 0.0) for y, q, k, c, a in bills])
        db.commit()
    return path, parcels


def test_build_without_bills_estimates_tax(tmp_path):
    path, parcels = make_store(tmp_path)
    out, meta = B.build(B.connect(path), "0906", B.load_positions(parcels))
    assert meta["tax_source"] == "estimated" and meta["base_year"] == 2023
    r = out["0906_100_1"]
    assert r["kind"] == "2_family" and r["tax"]["2026"] == round(501000 * 2.657 / 100)
    assert r["compare"]["count"] == 11 and r["compare"]["size_band"] == 0.10
    assert r["appeal"]["score"] in ("likely", "possible", "unlikely") and len(r["appeal"]["comparable_sales"]) == 5
    assert out["0906_200_1"]["appeal"]["score"] == "not_applicable"
    # identical rate-driven changes rank in the middle, not at the bottom
    assert 40 <= r["compare"]["city_percentile"] <= 60


def test_build_with_bills_marks_renovation_and_appeals(tmp_path):
    path, parcels = make_store(tmp_path, with_bills=True)
    out, meta = B.build(B.connect(path), "0906", B.load_positions(parcels))
    assert meta["tax_source"] == "bills" and meta["base_year"] == 2019
    r1 = out["0906_100_1"]
    assert r1["added_assessment_years"] == [2024] and r1["tax"]["2019"] == 10000
    assert any(n["pin"] == "0906_100_2" for n in r1["compare"]["list"])
    assert r1["appeals_nearby"]["won"] == 1 and r1["appeals_nearby"]["median_reduction"] == round(1000 / 12000, 4)
    assert out["0906_100_2"]["appeal_credits"] == {"2023": -1000}
    assert r1["appeal"]["score"] != "likely"                        # renovated: never "likely"


def test_output_has_no_private_fields(tmp_path):
    path, parcels = make_store(tmp_path)
    out, meta = B.build(B.connect(path), "0906", B.load_positions(parcels))
    B.write_json(out, meta, tmp_path / "site")
    text = "".join(p.read_text() for p in (tmp_path / "site").rglob("*.json"))
    for word in ("SAMPLE, OWNER", "PRIOR, OWNER", "MAIL ST", "MTG1", "owner", "mailing", "mortgage"):
        assert word not in text
    index = json.loads((tmp_path / "site" / "index.json").read_text())
    assert index["fields"] == B.SUMMARY_FIELDS and len(index["rows"]) == 13


def test_write_postgres_replaces_atomically(tmp_path):
    import os
    import pytest
    pg = os.environ.get("TEST_DATABASE_URL")
    if not pg:
        pytest.skip("set TEST_DATABASE_URL to run Postgres tests")
    import psycopg
    path, parcels = make_store(tmp_path)
    out, meta = B.build(B.connect(path), "0906", B.load_positions(parcels))
    with psycopg.connect(pg, autocommit=True) as c:
        c.execute(f"DROP SCHEMA IF EXISTS {B.SITE_SCHEMA} CASCADE")
    for _ in range(2):                                            # second run replaces, no duplicates
        B.write_postgres(B.connect(pg), out, meta)
    with psycopg.connect(pg, autocommit=True) as c:
        assert c.execute("SELECT COUNT(*) FROM site.properties").fetchone()[0] == 13
        row = c.execute("SELECT address, kind, data->'compare'->>'count' FROM site.properties "
                        "WHERE pin = '0906_100_1'").fetchone()
        assert row == ("1 SAMPLE ST.", "2_family", "11")
        assert c.execute("SELECT value->>'tax_source' FROM site.meta WHERE key='0906'").fetchone()[0] == "estimated"
        assert c.execute("SELECT pin FROM site.properties WHERE address ILIKE %s LIMIT 1", ("%sample%",)).fetchone()
