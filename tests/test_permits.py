"""Permit crawler (EnerGov) and how permits reach the site build: no network, a fake portal."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_site as B  # noqa: E402
import fetch_permits as F  # noqa: E402
from portals.energov import parse  # noqa: E402
from test_build_site import make_store  # noqa: E402

RESULT = {"CaseNumber": "CNST-26-1965", "CaseId": "abc", "MainParcel": "0906_16104_24_c0302",
          "AddressDisplay": "66 GAUTIER AVE Unit: APT 3R JERSEY CITY NJ 07306",
          "CaseType": "Construction Permit Application - Alteration/Renovation",
          "CaseWorkclass": "Construction Permit Application", "CaseStatus": "Issued",
          "ApplyDate": "2026-10-01T09:00:00", "IssueDate": "2026-10-23T14:00:00", "FinalDate": None,
          "ExpireDate": "2999-01-01T00:00:00", "Description": "INTERIOR DEMOLITION\nOF APARTMENT",
          "CompanyName": "SHOULD NOT BE KEPT", "HolderFirstName": "NOBODY"}


def permit(no, pin, ctype, issued, status="Issued", final=None, desc="work"):
    return {"permit_no": no, "case_id": no, "pin": pin, "address": "1 SAMPLE ST", "case_type": ctype, "work_class": "",
            "status": status, "apply_date": issued, "issue_date": issued, "final_date": final, "expire_date": None,
            "description": desc}


class FakePortal:
    def __init__(self, by_address=None, pages=None):
        self.by_address, self.pages, self.calls = by_address or {}, pages or [], []

    def permits_for(self, address):
        self.calls.append(address)
        return self.by_address.get(address, [])

    def permits_page(self, page, page_size=100, newest_first=True, keyword=""):
        self.calls.append(page)
        return (self.pages[page - 1] if page <= len(self.pages) else []), len(self.pages)


def test_parse_keeps_public_fields_only():
    r = parse(RESULT)
    assert r["permit_no"] == "CNST-26-1965" and r["issue_date"] == "2026-10-23" and r["expire_date"] is None
    assert r["description"] == "INTERIOR DEMOLITION OF APARTMENT"
    assert "SHOULD NOT" not in str(r) and "NOBODY" not in str(r)


def test_categories_and_relevance():
    assert F.category("Construction Permit Application - New Construction") == "new_construction"
    assert F.category("Construction Permit Application - Alteration/Renovation") == "renovation"
    assert F.category("Plumbing Subcode Technical Section", "Plumbing Permit") == "trade"
    assert F.category("Plumbing Subcode Technical Section - Minor Work") == "minor"
    assert F.category("MUA - Water Meter") == "utility" and F.category("Certificate-CO") == "certificate"
    assert F.category("Complete Demolition") == "demolition"
    assert F.tax_relevance("renovation", "replace boiler in kind") == "unlikely"
    assert F.tax_relevance("renovation", "Add a third floor and roof deck") == "likely"
    assert F.tax_relevance("renovation", "kitchen and bath renovation") == "possible"
    assert F.tax_relevance("addition") == "likely" and F.tax_relevance("demolition") == "lower"


def test_addresses_and_pins():
    assert F.search_address("66 GAUTIER AVE.") == "66 GAUTIER AVE"
    assert F.search_address("100-102 MONTGOMERY ST.") == "100 MONTGOMERY ST"
    assert F.normalize_pin("0906_26102_8_c4102") == "0906_26102_8_C4102"
    assert F.lot_of("0906_16104_24_C0302") == "0906_16104_24" and F.lot_of("0906_1_2") == "0906_1_2"


def test_backfill_keeps_the_lots_permits_and_resumes(tmp_path):
    path, _ = make_store(tmp_path)
    db = F.open_db(path)
    portal = FakePortal({"1 SAMPLE ST": [
        permit("A-1", "0906_100_1", "Construction Permit Application - Addition", "2024-05-01"),
        permit("A-2", "0906_999_9", "Construction Permit Application - Addition", "2024-05-01"),   # other lot
    ]})
    searched, stored, left = F.backfill(db, portal, log=lambda *_: None)
    assert (searched, stored, left) == (1, 1, 0)        # the 13 lots share one address: one search
    assert db.execute("SELECT lot, category FROM permits WHERE permit_no='A-1'").fetchone() == ("0906_100_1", "addition")
    assert not db.execute("SELECT 1 FROM permits WHERE permit_no='A-2'").fetchone()
    portal.calls.clear()
    assert F.backfill(db, portal, log=lambda *_: None)[0] == 0 and not portal.calls       # all fresh: nothing to do


def test_recent_stops_after_the_window(tmp_path):
    path, _ = make_store(tmp_path)
    db = F.open_db(path)
    pages = [[permit("N-1", "0906_100_2", "Complete Demolition", "2026-10-20")],
             [permit("N-2", "0906_100_2", "Complete Demolition", "2026-07-01")],
             [permit("N-3", "0906_100_2", "Complete Demolition", "2026-01-01")]]
    portal = FakePortal(pages=pages)
    assert F.recent(db, portal, days=45, today=date(2026, 10, 27)) == 2 and portal.calls == [1, 2]


def test_site_build_permits_outlook_and_appeal(tmp_path):
    path, parcels = make_store(tmp_path, with_bills=True)
    db = F.open_db(path)
    F.upsert(db, [
        permit("A-1", "0906_100_3", "Construction Permit Application - Addition", "2026-03-01", desc="rear addition"),
        permit("A-2", "0906_100_3", "Plumbing Subcode Technical Section", "2026-03-01"),           # trade: hidden
        permit("A-3", "0906_100_4", "Construction Permit Application - Alteration/Renovation", "2025-01-10",
               status="Complete", final="2025-06-01", desc="finish basement"),
        permit("A-4", "0906_100_5", "Construction Permit Application - Alteration/Renovation", "2025-02-01",
               desc="replace boiler"),
    ], "2026-10-27")
    db.commit()
    out, meta = B.build(B.connect(path), "0906", B.load_positions(parcels), today=date(2026, 10, 27))
    p3, p4, p5 = (out[f"0906_100_{i}"]["permits"] for i in (3, 4, 5))
    assert [x["no"] for x in p3["list"]] == ["A-1"] and p3["outlook"]["state"] == "in_progress"
    assert p4["outlook"]["state"] == "may_be_added" and p4["renovated"]
    assert p5["outlook"] is None and not p5["renovated"]          # a boiler swap doesn't change the assessment
    assert out["0906_100_4"]["appeal"]["score"] != "likely"
    assert meta["permits"] is True


def test_map_changes(tmp_path):
    path, parcels = make_store(tmp_path, with_bills=True)
    out, meta = B.build(B.connect(path), "0906", B.load_positions(parcels))
    r = out["0906_100_5"]
    # bills grow 5% of the 2019 amount a year: Q4 2026 = 2500 * 1.35, Q4 2025 = 2500 * 1.30
    assert r["change_q4"] == round(1.35 / 1.30 - 1, 4) and r["change_5y"] == round(1.35 / 1.10 - 1, 4)
    assert r["q4_bill"] == {"2025": 3250, "2026": 3375}
    assert meta["median_change_q4"] == r["change_q4"] and meta["trend_years"] == 5
    est, _ = B.build(B.connect(make_store(tmp_path / "e")[0]), "0906", B.load_positions(parcels))
    e = est["0906_100_1"]
    assert e["change_5y"] is None and e["change_q4"] is not None       # no 2021 assessment without bills
