"""Similar-property matching and the appeal screen, on synthetic properties."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import comparables as C  # noqa: E402

LAT, LON = 40.7300, -74.0600
MI_LAT = 1 / 69.0   # degrees of latitude per mile, roughly


def prop(pin, sq_ft=2000, year=1900, mi=0.1, kind="2_family", building=None, sale=None, assessment=None):
    sd, sp = sale or (None, None)
    return C.Prop(pin, f"{pin} ST", kind, sq_ft, year, 2.0, "F", LAT + mi * MI_LAT, LON, building or pin,
                  assessment, sd, sp, "0" if sale else None)


def test_parsers():
    assert C.units_from("3S-BT-F-D-3U") == 3 and C.units_from("2BR/2BA PS#6") is None
    assert C.units_from("", dwellings=2) == 2
    assert C.stories_from("2.5S-F-D-1U-H") == 2.5 and C.construction_from("2S-F-D-2U") == "F"
    assert C.kind("2", "", 1) == "single_family" and C.kind("2", "", 3) == "3_family"
    assert C.kind("2", "C0310", None) == "condo" and C.kind("4A", "", None) is None
    assert C.era(1880) == "pre1940" and C.era(1975) == "1940_1999" and C.era(2006) == "2000plus"


def test_size_band_and_era_filter_and_distance_order():
    subject = prop("S", mi=0)
    others = [prop(f"N{i}", sq_ft=2000 + 30 * i, mi=0.02 * i) for i in range(1, 10)]   # +1.5% .. +13.5%
    others += [prop("BIG", sq_ft=2500, mi=0.01), prop("NEW", year=2010, mi=0.01), prop("FAR", mi=3)]
    m = C.neighbors(C.Index([subject, *others]), subject)
    pins = [p.pin for p, _, _ in m.props]
    # only 6 are within +/-10% (fewer than 8, at any distance), so the band widens to +/-15%
    assert m.size_band == 0.15 and m.radius_mi == 0.25
    assert sorted(pins) == [f"N{i}" for i in range(1, 10)]
    assert "BIG" not in pins and "NEW" not in pins and "FAR" not in pins
    assert pins[0] == "N1"                                      # closest and most similar first
    # with 8 inside +/-10% it stays at 10%
    tight = [prop(f"T{i}", sq_ft=2050, mi=0.02 * i) for i in range(1, 9)]
    m = C.neighbors(C.Index([subject, *tight, *others]), subject)
    assert m.size_band == 0.10 and all(abs(p.sq_ft / 2000 - 1) <= 0.10 for p, _, _ in m.props)


def test_widens_distance_before_size_and_stops_at_15_percent():
    subject = prop("S", mi=0)
    # 8 matches at +12% size close by, 8 at +5% size 0.8 mi away: distance widens first, so the far ones win
    near_big = [prop(f"A{i}", sq_ft=2240, mi=0.05) for i in range(8)]
    far_ok = [prop(f"B{i}", sq_ft=2100, mi=0.8) for i in range(8)]
    m = C.neighbors(C.Index([subject, *near_big, *far_ok]), subject)
    assert m.size_band == 0.10 and m.radius_mi == 1.0 and {p.pin[0] for p, _, _ in m.props} == {"B"}
    # only +20% matches exist: nothing is returned beyond +/-15%
    m = C.neighbors(C.Index([subject, *[prop(f"C{i}", sq_ft=2400) for i in range(10)]]), subject)
    assert m.props == [] and "Not enough" in m.reason


def test_condo_cap_per_building_and_sales_rules():
    subject = prop("U1", sq_ft=800, year=2006, kind="condo", building="BLD", mi=0)
    same = [prop(f"U{i}", sq_ft=800, year=2006, kind="condo", building="BLD", mi=0) for i in range(2, 12)]
    other = [prop(f"V{i}", sq_ft=800, year=2006, kind="condo", building=f"B{i}", mi=0.1) for i in range(5)]
    m = C.neighbors(C.Index([subject, *same, *other]), subject)
    assert sum(1 for p, _, _ in m.props if p.building == "BLD") == 5
    sold = [prop(f"S{i}", sq_ft=800, year=2006, kind="condo", building="BLD", mi=0,
                 sale=("2026-03-01", 400000)) for i in range(4)]
    old = [prop("OLD", sq_ft=800, year=2006, kind="condo", building="X", sale=("2023-06-01", 300000))]
    sm = C.sales(C.Index([subject, *sold, *old]), subject)
    assert len(sm.props) == 2 and "OLD" not in [p.pin for p, _, _ in sm.props]   # 2 per building, 2024+


def test_appeal_screen_uses_the_towns_range():
    comps = [prop(f"0906_S{i}", sq_ft=2000, sale=("2026-01-01", 1_000_000)) for i in range(3)]   # $500/sq ft
    match = C.Match([(p, 0.1, 1.0) for p in comps], 0.10, 0.25)
    jc = prop("0906_1_1", assessment=800_000)    # value 1,000,000 -> 80% > 76.69%
    assert C.appeal(jc, match)["score"] == "likely"
    uc = prop("0910_1_1", assessment=800_000)    # same 80%, but Union City's range is 79.99-108.23%
    assert C.appeal(uc, match)["score"] == "unlikely"
    assert C.appeal(prop("0906_1_1", assessment=700_000), match)["score"] == "possible"
    thin = C.Match(match.props[:2], 0.10, 1.0)
    assert C.appeal(jc, thin)["score"] == "not_enough_data"


def test_likely_needs_agreeing_sales_and_no_recent_renovation():
    def match(prices):
        comps = [prop(f"0906_S{i}", sq_ft=2000, sale=("2026-01-01", v)) for i, v in enumerate(prices)]
        return C.Match([(p, 0.1, 1.0) for p in comps], 0.10, 0.25)
    jc = prop("0906_1_1", assessment=800_000)
    tight = match([950_000, 1_000_000, 1_050_000])           # spread 10%
    wide = match([700_000, 1_000_000, 1_300_000])            # spread 60%
    assert C.appeal(jc, tight)["score"] == "likely"
    r = C.appeal(jc, wide)
    assert r["score"] == "possible" and "vary widely" in r["notes"][0]
    r = C.appeal(jc, tight, renovated=True)
    assert r["score"] == "possible" and r["notes"] == [C.RENOVATION_NOTE]
    assert C.appeal(prop("0906_1_1", assessment=600_000), tight, renovated=True)["score"] == "unlikely"
