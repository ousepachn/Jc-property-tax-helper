"""Offline tests for the billing-portal parsers, using sanitized recorded responses."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from portals.hls import account_from_list_row, parse_details  # noqa: E402
from portals.models import Account, categorize, make_pin, pin_part  # noqa: E402
from portals.wipp import gwt_long, parse_account, parse_key, parse_response, parse_search, rpc_body  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def test_pin_helpers_match_pams_pin_format():
    assert pin_part("00301", "    ") == "301"
    assert pin_part("00001", "  01") == "1.01"
    assert make_pin("0910", "39.01", "9", "C0602   ") == "0910_39.01_9_C0602"
    assert make_pin("0906", "301", "1", "") == "0906_301_1"


@pytest.mark.parametrize("kind,category", [
    ("tax", "property_tax"), ("added", "property_tax"), ("omitted", "property_tax"),
    ("cancel_tax_court_adjustment", "appeal_adjustment"), ("refund_hudson_cty_bd_adjustment", "appeal_adjustment"),
    ("assessor_adjustment", "appeal_adjustment"), ("hotel_tax_adjustment", "other"), ("water", "other"),
    ("nsf_chk_reversal_adjustment", "other"),
])
def test_categorize(kind, category):
    assert categorize(kind) == category


# --- WIPP (Edmunds GWT-RPC) -------------------------------------------------

def test_rpc_body_matches_browser_request():
    captured = ("7|0|9|https://wipp.edmundsassoc.com/Wipp/wipp/|D5E8FE1926F7761CD5A2EA6F4F52F53E|"
                "wipp.client.WippService|taxBlqIdSearch|java.lang.String/2004016611|Z|0910|"
                "   39  01    9       C0603   ||1|2|3|4|4|5|5|5|6|7|8|9|1|")
    assert rpc_body("taxBlqIdSearch", [("S", "0910"), ("S", "   39  01    9       C0603   "),
                                       ("S", ""), ("Z", True)]) == captured


@pytest.mark.parametrize("token,value", [("A", 0), ("B", 1), ("BA", 64), ("fQA", 128000)])
def test_gwt_long(token, value):
    assert gwt_long(token) == value


def test_parse_response_handles_js_escapes_and_longs():
    ints, strings = parse_response("//OK[1,'BA',2,[\"A \\x26 B\",\"x\"],0,7]")
    assert ints == [1, 64, 2]
    assert strings == ["A & B", "x"]


def test_parse_key():
    assert parse_key("   39  01    9       C0602   ") == ("39.01", "9", "C0602")
    assert parse_key("  100        2               ") == ("100", "2", "")


def test_parse_search_fixture():
    rows = parse_search((FIX / "wipp_0910_search.txt").read_text())
    assert len(rows) == 20
    assert rows[0][0] == "  100        1               "
    assert len({k for k, _ in rows}) == 20


def _with_fake_strings(text):
    """Replace the fixture's REDACTED strings with distinct fake values FAKE0, FAKE1, ..."""
    i, j = text.find(',["'), text.rfind('"]')
    table = json.loads(text[i + 1:j + 2])
    n = iter(range(len(table)))
    table = [f"FAKE{next(n)}" if s == "REDACTED" else s for s in table]
    return text[:i + 1] + json.dumps(table) + text[j + 2:]


def test_parse_account_owner_fields_by_position():
    key = "  100        2               "
    res = parse_account(_with_fake_strings((FIX / "wipp_0910_100_2.txt").read_text()), key, "0910", "wipp:0910")
    a = res.account
    assert a.owner_name and a.owner_name.startswith("FAKE")
    assert a.mailing_address and a.mailing_address.startswith("FAKE") and a.mailing_address != a.owner_name
    assert a.mailing_zip and a.mailing_zip.isdigit() and len(a.mailing_zip) == 5
    assert res.raw is not None


def test_parse_account_fixture():
    key = "  100        2               "
    res = parse_account((FIX / "wipp_0910_100_2.txt").read_text(), key, "0910", "wipp:0910")
    a = res.account
    assert a.pin == "0910_100_2"
    # Matches the 2026 MOD-IV list: land 242,200 + improvement 351,800 = 594,000
    assert (a.land_value, a.improvement_value, a.net_taxable) == (242200, 351800, 594000)
    by_year = {}
    for b in res.bills:
        assert b.category == "property_tax"
        by_year.setdefault(b.tax_year, []).append(b)
    assert {b.quarter for b in by_year[2026]} == {1, 2, 3, 4}
    # Union City 2026 billing rate: 1.859 general - 0.238 REAP credit = 1.621 per $100
    assert sum(b.amount for b in by_year[2026]) == pytest.approx(594000 * 0.01621, abs=0.05)
    q = {b.quarter: b.amount for b in by_year[2026]}
    assert q[3] + q[4] > q[1] + q[2]


# --- HLS (Jersey City) -------------------------------------------------------

def test_hls_list_row_to_account():
    row = {"AccountNumber": 138289, "SortBlock": "00301", "SortBlockSuffix": "    ", "SortLot": "00001",
           "SortLotSuffix": "  01", "Qualifier": "C0002      ", "PropertyLocation": "677 LIBERTY AVE.   ",
           "Class": " 2 ", "OwnerName": "DOE, JANE  ", "Address": "1 MAIN ST", "CityState": "JERSEY CITY, NJ",
           "PostalCode": "07302", "DanielsLaw": False}
    a = account_from_list_row(row, "0906")
    assert a.pin == "0906_301_1.01_C0002"
    assert a.property_location == "677 LIBERTY AVE."
    # parsed at the client; whether it is stored is the crawler's decision (--include-owners)
    assert (a.owner_name, a.mailing_address, a.mailing_zip, a.daniels_law) == ("DOE, JANE", "1 MAIN ST", "07302", False)


def test_hls_parse_details_fixture():
    vm = json.loads((FIX / "hls_jc_313_new_york.json").read_text())["accountInquiryVM"]
    acct = Account("0906", "98624", "0906_2306_46")
    bills = parse_details(vm, acct, "hls:JerseyCity")
    assert acct.net_taxable == 520400
    tax = lambda y: round(sum(b.amount for b in bills if b.tax_year == y and b.category == "property_tax"), 2)  # noqa: E731
    assert tax(2025) == 12151.34          # equals MOD-IV 2026 last_year_tax
    assert tax(2026) == 13827.03          # 520,400 x 2.657%
    q26 = {b.quarter: b.amount for b in bills if b.tax_year == 2026 and b.kind == "tax"}
    assert q26 == {1: 3037.84, 2: 3037.83, 3: 3852.26, 4: 3899.10}
    assert all(b.amount != 0 for b in bills)
