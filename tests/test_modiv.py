import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from modiv import FIELDS, norm_block_lot, parse_line, parse_signed  # noqa: E402


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("00126604H", 12660.48),
        ("00000000{", 0.0),
        ("00029012H", 2901.28),
        ("00006029}", -602.90),
        ("00006029J", -602.91),
        ("000000123", 1.23),
        ("         ", None),
    ],
)
def test_parse_signed_overpunch(raw, expected):
    assert parse_signed(raw) == expected


def test_layout_fields_are_within_record_and_non_overlapping():
    spans = sorted((s, e) for _, s, e, _ in FIELDS)
    for (s1, e1), (s2, _) in zip(spans, spans[1:]):
        assert e1 < s2
    assert spans[-1][1] <= 700


def _record(**fields):
    line = [" "] * 700
    for name, start, end, _ in FIELDS:
        if name in fields:
            val = fields[name]
            assert len(val) == end - start + 1, name
            line[start - 1:end] = val
    return "".join(line)


def test_parse_line_builds_pin_and_values():
    line = _record(
        county_district="0906", block="00301    ", lot="00001  01", qualifier="C0001      ",
        record_id="20", property_class="2  ", net_value="000416500",
        last_year_tax="00097252H", exempt_statute="40A:20-1    ",
    )
    rec = parse_line(line)
    assert rec["municipality"] == "Jersey City"
    assert rec["pin"] == "0906_301_1.01_C0001"
    assert rec["net_value"] == 416500
    assert rec["last_year_tax"] == 9725.28
    assert rec["exempt_statute"] == "40A:20-1"


@pytest.mark.parametrize(
    "raw,expected",
    [("00301    ", "301"), ("00001  01", "1.01"), ("00012    ", "12"), ("00000    ", "0"), ("000070001", "7.0001")],
)
def test_norm_block_lot(raw, expected):
    assert norm_block_lot(raw) == expected
