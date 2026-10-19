import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from owners import classify, classify_all, parse_street, same_address  # noqa: E402


@pytest.mark.parametrize("addr,expected", [
    ("413-15 9TH ST #602", ({413, 414, 415}, "9TH ST")),
    ("1021 Grand Street, Apt 4A", ({1021}, "GRAND ST")),
    ("307 SECOND ST", ({307}, "2ND ST")),
    ("PO BOX 123", (set(), "")),
])
def test_parse_street(addr, expected):
    assert parse_street(addr) == expected


@pytest.mark.parametrize("prop,mail,same", [
    ("413-15 9TH ST", "413 9TH ST #602", True),
    ("1021 GRAND ST", "1021 GRAND STREET UNIT 4", True),
    ("307 SECOND ST", "307 2ND ST", True),
    ("307 SECOND ST", "309 2ND ST", False),
    ("56 PARK AVE", "56 PARK PL", True),     # suffix ignored: same name, known limitation
    ("56 PARK AVE", "PO BOX 56", False),
])
def test_same_address(prop, mail, same):
    assert same_address(prop, mail) is same


def row(name, loc="10 MAIN ST", mail="10 MAIN ST", zip_="07030"):
    return {"owner_name": name, "property_location": loc, "mailing_address": mail, "mailing_zip": zip_}


@pytest.mark.parametrize("r,portfolio,expected", [
    (row("DOE, JANE"), 1, "owner_occupied"),
    (row("DOE, JANE", mail="99 OTHER AVE"), 1, "individual_investor"),
    (row("10 MAIN ST LLC", mail="1 OFFICE PL"), 1, "small_llc"),
    (row("10 MAIN ST LLC", mail="1 OFFICE PL"), 7, "corporate"),
    (row("ACME REALTY INC", mail="1 OFFICE PL"), 1, "corporate"),
    (row("SMITH FAMILY TRUST", mail="5 ELM ST"), 1, "trust_estate"),
    (row("HOBOKEN HOUSING AUTHORITY"), 30, "public_nonprofit"),
    (row(None), 0, "unknown"),
])
def test_classify(r, portfolio, expected):
    assert classify(r, portfolio) == expected


def test_portfolio_counts_entities_sharing_a_mailing_address():
    rows = [row(f"{i} WASHINGTON ST LLC", loc=f"{i} WASHINGTON ST", mail="200 OFFICE BLVD") for i in range(6)]
    rows.append(row("DOE, JANE", mail="200 OFFICE BLVD"))   # individuals don't join the entity group
    out = classify_all(rows)
    assert all(c == "corporate" and n == 6 for c, n in out[:6])
    assert out[6][0] == "individual_investor"


def test_care_of_party_groups_single_asset_llcs():
    rows = [row(f"{a} LLC % HOTHEM", loc=f"{a} WASHINGTON ST", mail=f"{a} WASHINGTON ST") for a in
            ("450 SEVENTH", "320 WASHINGTON ST", "510 ADAMS", "1 HUDSON", "2 HUDSON")]
    assert all(c == "corporate" for c, _ in classify_all(rows))


@pytest.mark.parametrize("name,expected", [
    ("PUBLIC SERVICE ELECTRIC & GAS CO", "corporate"),
    ("JEFFERSON ASSOCIATION LLC", "small_llc"),
    ("58 EIGHT ST CONDO ASSOC", "public_nonprofit"),
])
def test_name_rules(name, expected):
    assert classify(row(name, mail="1 ELSEWHERE AVE"), 1) == expected


@pytest.mark.parametrize("pin,cls,dwellings,expected", [
    ("0905_155_3_C0PHG", "2", None, "condo"),
    ("0905_33_18.02", "2", 1, "single_family"),
    ("0905_33_20", "2", 3, "two_to_four_family"),
    ("0905_33_21", "2", None, "home_units_unknown"),
    ("0905_1_1", "4C", None, "apartment_5plus"),
    ("0905_1_2", "4A", None, "commercial"),
    ("0905_194_47", "1", None, "vacant_land"),
    ("0905_1_15", "15F", None, "exempt"),
    ("0905_102_25", "", None, "no_class_on_file"),
])
def test_property_type(pin, cls, dwellings, expected):
    from analyze_delinquency import property_type
    assert property_type(pin, cls, dwellings) == expected


def test_newest_lien_year():
    from analyze_delinquency import newest_lien_year
    assert newest_lien_year('[{"sale_date": "1985-10-30"}, {"sale_date": "2025-12-17"}]') == 2025
    assert newest_lien_year('[{"sale_date": null}]') == 0
    assert newest_lien_year("") == 0
