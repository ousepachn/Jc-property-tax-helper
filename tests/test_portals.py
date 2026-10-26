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
    assert make_pin("0910", "88.02", "7", "C0310   ") == "0910_88.02_7_C0310"
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
                "   88  02    7       C0311   ||1|2|3|4|4|5|5|5|6|7|8|9|1|")
    assert rpc_body("taxBlqIdSearch", [("S", "0910"), ("S", "   88  02    7       C0311   "),
                                       ("S", ""), ("Z", True)]) == captured


@pytest.mark.parametrize("token,value", [("A", 0), ("B", 1), ("BA", 64), ("fQA", 128000)])
def test_gwt_long(token, value):
    assert gwt_long(token) == value


def test_parse_response_handles_js_escapes_and_longs():
    ints, strings = parse_response("//OK[1,'BA',2,[\"A \\x26 B\",\"x\"],0,7]")
    assert ints == [1, 64, 2]
    assert strings == ["A & B", "x"]


def test_parse_key():
    assert parse_key("   88  02    7       C0310   ") == ("88.02", "7", "C0310")
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
    vm = json.loads((FIX / "hls_jc_sample.json").read_text())["accountInquiryVM"]
    acct = Account("0906", "90001", "0906_9901_1")
    bills = parse_details(vm, acct, "hls:JerseyCity")
    assert acct.net_taxable == 450000
    tax = lambda y: round(sum(b.amount for b in bills if b.tax_year == y and b.category == "property_tax"), 2)  # noqa: E731
    assert tax(2025) == 10507.49          # 450,000 x 2.335%
    assert tax(2026) == 11956.50          # 450,000 x 2.657%
    q26 = {b.quarter: b.amount for b in bills if b.tax_year == 2026 and b.kind == "tax"}
    assert q26 == {1: 2626.88, 2: 2626.87, 3: 3331.12, 4: 3371.63}
    assert all(b.amount != 0 for b in bills)


# --- Delinquency -----------------------------------------------------------------

def test_past_due_respects_grace_period_and_categories():
    from datetime import date
    from portals.models import Bill, past_due

    bills = [
        Bill("p", "a", 2026, 3, "2026-08-01", "tax", 1000.0, balance=1000.0, interest=40.0),
        Bill("p", "a", 2026, 4, "2026-11-01", "tax", 1000.0, balance=1000.0),       # not yet due
        Bill("p", "a", 2026, 2, "2026-05-01", "tax", 1000.0, balance=0.0),          # paid
        Bill("p", "a", 2026, 3, "2026-08-01", "water", 50.0, balance=50.0),          # not property tax
    ]
    assert past_due(bills, date(2026, 10, 18)) == {
        "past_due_amount": 1000.0, "past_due_interest": 40.0, "past_due_bills": 1, "oldest_past_due": "2026-08-01"}
    assert past_due(bills, date(2026, 11, 5))["past_due_bills"] == 1        # inside the 10-day grace
    assert past_due(bills, date(2026, 11, 12))["past_due_bills"] == 2


def test_delinquency_level():
    from portals.models import delinquency_level
    assert delinquency_level(0) == "current"
    assert delinquency_level(1) == "1_quarter"
    assert delinquency_level(3) == "2_3_quarters"
    assert delinquency_level(5) == "4plus_quarters"
    assert delinquency_level(0, lien_count=1) == "lien"
    assert delinquency_level(0, pending_tax_sale=True) == "lien"


def test_hls_balances_and_flags():
    vm = json.loads((FIX / "hls_jc_sample.json").read_text())["accountInquiryVM"]
    acct = Account("0906", "90001", "0906_9901_1")
    bills = parse_details(vm, acct, "hls:JerseyCity")
    q = {(b.tax_year, b.quarter): b for b in bills if b.kind == "tax"}
    assert q[(2026, 4)].balance == 3371.63          # due Nov 1, unpaid when fetched
    assert q[(2026, 3)].balance == 0.0
    assert acct.portal_delinquent is False and acct.pending_tax_sale is False
    # its 2025 tax-sale certificate was redeemed: history, not an open lien
    assert (acct.lien_count, acct.redeemed_liens, acct.lien_open_balance) == (0, 1, 0)


def test_wipp_balances_from_fixture():
    res = parse_account((FIX / "wipp_0910_100_2.txt").read_text(), "  100        2               ", "0910", "wipp:0910")
    taxes = [b for b in res.bills if b.kind == "tax"]
    assert all(b.balance is not None and b.balance >= 0 for b in taxes)
    # everything due before the fixture was recorded (Oct 2026) and past grace is paid
    from datetime import date
    from portals.models import past_due
    assert past_due(res.bills, date(2026, 10, 18))["past_due_bills"] == 0
    assert sum(b.balance for b in taxes if b.due_date >= "2026-11-01") > 0


def test_wipp_lien_flags_and_details():
    key = "  194       47               "
    res = parse_account((FIX / "wipp_0905_194_47_lien.txt").read_text(), key, "0905", "wipp:0905")
    a = res.account
    assert a.pin == "0905_194_47" and a.property_class == "1" and a.net_taxable == 1900
    assert a.lien_count == 1 and a.pending_tax_sale is False and a.bankruptcy is False
    (lien,) = a.liens
    assert (lien["certificate"], lien["sale_date"], lien["sale_amount"], lien["subsequent_charges"]) == \
        ("003212", "1985-10-30", 35.19, 1808.07)
    assert a.lien_open_balance == 1843.26
    from portals.models import delinquency_level
    assert delinquency_level(0, a.lien_count, a.pending_tax_sale) == "lien"


def test_wipp_account_with_utility_account():
    # Union City accounts that also have a water/sewer account embed a UtilAcct (490 fields)
    key = "    8        3               "
    res = parse_account((FIX / "wipp_0910_8_3_util.txt").read_text(), key, "0910", "wipp:0910")
    a = res.account
    assert a.pin == "0910_8_3" and a.property_class == "2" and a.net_taxable == 259600
    assert a.owner_name == "OWNER NAME"
    assert len(res.bills) == 16 and {b.kind for b in res.bills} == {"tax", "credit"}
