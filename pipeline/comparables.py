"""Similar properties: for comparing tax changes and for appeal comparable sales.

Matching never uses assessed value, so an over-assessed property is not compared with properties
worth more. A property is similar when it is:
  - the same type (single-family, 2-4 family with the same number of units, condo),
  - within +/-10% of its floor area (widened to +/-15% only when too few match),
  - from the same era (built before 1940, 1940-1999, 2000 or later),
  - nearby: 1/4 mile, then 1/2 mile, then 1 mile, stopping once enough match.
Matches are ranked by a score of distance, size, age and the building code's stories and construction.
Condos look in their own building first and take at most 5 units from any one building.

Comparable sales are similar properties whose last sale carries SR-1A nonusable code 0 (the state's
"usable" market-sale flag), from 2024 on, at most 2 per building.
"""
import math
import re
from dataclasses import dataclass, field
from datetime import date

SIZE_BANDS = (0.10, 0.15)
RINGS_MI = (0.25, 0.5, 1.0)
KM_PER_MI = 1.609344
MIN_NEIGHBORS, MAX_NEIGHBORS = 8, 25
MIN_SALES, MAX_SALES = 3, 5
MAX_PER_BUILDING = {"neighbors": 5, "sales": 2}
SALES_FROM = "2024-01-01"
VALUATION_DATE = date(2026, 10, 1)
# NJ Chapter 123 average ratio and common level range for tax year 2027, by municipality
# (Division of Taxation, "Certification of the 2026 average ratios", 2027CH123.pdf)
RATIO_YEAR = 2027
RATIOS = {
    "0905": {"avg": 0.5586, "lo": 0.4748, "hi": 0.6424},   # Hoboken
    "0906": {"avg": 0.6669, "lo": 0.5669, "hi": 0.7669},   # Jersey City
    "0910": {"avg": 0.9411, "lo": 0.7999, "hi": 1.0823},   # Union City
}
SQFT_RANGE = (300, 20000)
# "likely" needs comparable sales that agree: (max - min) / median of their $/sq ft at most this
MAX_SPREAD_LIKELY = 0.35
RENOVATION_NOTE = ("This property had an added assessment or building work in the last 5 years. Renovated "
                   "properties often sell above the average-condition sales used here, so the estimate may be low.")


def era(year_built):
    if not year_built:
        return None
    return "pre1940" if year_built < 1940 else "1940_1999" if year_built < 2000 else "2000plus"


def units_from(desc, dwellings=None):
    m = re.search(r"(\d+)U\b", desc or "")
    if m:
        return int(m.group(1))
    return int(dwellings) if dwellings else None


def stories_from(desc):
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*S", desc or "")
    return float(m.group(1)) if m else None


def construction_from(desc):
    """'2S-F-D-2U' -> 'F' (frame); 'B' brick, 'BT' basement token is skipped."""
    parts = (desc or "").split("-")[1:]
    for p in parts:
        p = p.strip()
        if p in ("F", "B", "B+F", "M", "S", "C", "A"):
            return p
    return None


def kind(prop_class, qualifier, units):
    if prop_class != "2":
        return None                      # v1 compares residential class 2 only
    if (qualifier or "").startswith("C"):
        return "condo"
    if units == 1:
        return "single_family"
    if units and 2 <= units <= 4:
        return f"{units}_family"
    return None


@dataclass
class Prop:
    pin: str
    address: str
    kind: str | None
    sq_ft: int | None
    year_built: int | None
    stories: float | None
    construction: str | None
    lat: float | None
    lon: float | None
    building: str                        # base block/lot: condo units in one building share it
    assessment: float | None = None
    sale_date: str | None = None
    sale_price: float | None = None
    nu_code: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def era(self):
        return era(self.year_built)

    @property
    def usable_size(self):
        return self.sq_ft and SQFT_RANGE[0] <= self.sq_ft <= SQFT_RANGE[1]

    @property
    def usable_sale(self):
        return (self.nu_code == "0" and self.sale_price and self.sale_price > 0 and self.sale_date
                and SALES_FROM <= self.sale_date <= date.today().isoformat())


def miles(a, b):
    if None in (a.lat, a.lon, b.lat, b.lon):
        return math.inf
    k = math.cos(math.radians((a.lat + b.lat) / 2))
    dx, dy = (a.lon - b.lon) * k * 111.32, (a.lat - b.lat) * 111.32
    return math.hypot(dx, dy) / KM_PER_MI


class Index:
    """Grid of properties by kind for fast radius queries."""

    CELL = 0.01   # degrees, about 0.7 mile

    def __init__(self, props):
        self.cells = {}
        for p in props:
            if p.kind and p.lat is not None and p.usable_size:
                key = (p.kind, int(p.lat / self.CELL), int(p.lon / self.CELL))
                self.cells.setdefault(key, []).append(p)

    def near(self, subject, radius_mi):
        r = math.ceil(radius_mi * KM_PER_MI / 111.32 / self.CELL / 0.75) + 1
        cy, cx = int(subject.lat / self.CELL), int(subject.lon / self.CELL)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                for p in self.cells.get((subject.kind, cy + dy, cx + dx), ()):
                    if p.pin != subject.pin:
                        d = miles(subject, p)
                        if d <= radius_mi:
                            yield p, d


def score(subject, p, d):
    """Lower is more similar: distance, size, age and building-code differences on one scale."""
    s = d / 0.25                                                   # a quarter mile = 1 point
    s += abs(p.sq_ft / subject.sq_ft - 1) / 0.05                   # 5% size difference = 1 point
    if subject.year_built and p.year_built:
        s += abs(p.year_built - subject.year_built) / 20           # 20 years = 1 point
    if subject.stories and p.stories and subject.stories != p.stories:
        s += 1
    if subject.construction and p.construction and subject.construction != p.construction:
        s += 1
    if subject.kind == "condo" and p.building == subject.building:
        s -= 2                                                     # same building first
    return s


@dataclass
class Match:
    props: list            # [(Prop, miles, score)]
    size_band: float | None
    radius_mi: float | None
    reason: str = ""


def find(index, subject, want, minimum, per_building, accept=lambda p: True):
    """Widen distance first, then size; stop at the first combination with enough matches."""
    if not subject.kind:
        return Match([], None, None, "This property type is not compared in this version.")
    if not subject.usable_size:
        return Match([], None, None, "The county has no usable floor area for this property.")
    if subject.lat is None:
        return Match([], None, None, "This property has no map position.")
    best = Match([], None, None)
    for band in SIZE_BANDS:
        for radius in RINGS_MI:
            cand = []
            for p, d in index.near(subject, radius):
                if abs(p.sq_ft / subject.sq_ft - 1) > band + 1e-9:
                    continue
                if subject.era and p.era != subject.era:
                    continue
                if not accept(p):
                    continue
                cand.append((p, d, score(subject, p, d)))
            cand.sort(key=lambda t: t[2])
            picked, per = [], {}
            for t in cand:
                b = t[0].building
                if per.get(b, 0) >= per_building:
                    continue
                per[b] = per.get(b, 0) + 1
                picked.append(t)
                if len(picked) == want:
                    break
            m = Match(picked, band, radius)
            if len(picked) >= minimum:
                return m
            if len(picked) > len(best.props):
                best = m
    best.reason = "Not enough similar properties nearby."
    return best


def neighbors(index, subject):
    return find(index, subject, MAX_NEIGHBORS, MIN_NEIGHBORS, MAX_PER_BUILDING["neighbors"])


def sales(index, subject):
    return find(index, subject, MAX_SALES, MIN_SALES, MAX_PER_BUILDING["sales"], accept=lambda p: p.usable_sale)


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def appeal(subject, sale_match, renovated=False):
    """Rough appeal screen from comparable sales' price per square foot, against the town's 2027 range.

    renovated: the property had an added assessment or completed building work in the last 5 years;
    its value is then likely above the average-condition sales, so "likely" becomes "possible"."""
    comps = [p for p, _, _ in sale_match.props]
    rr = RATIOS.get(subject.pin[:4])
    if not rr:
        return {"score": "not_applicable", "reason": "No common level range on file for this town."}
    if not subject.assessment:
        return {"score": "not_applicable", "reason": "No taxable assessment to appeal."}
    if len(comps) < MIN_SALES:
        return {"score": "not_enough_data", "reason": sale_match.reason or "Fewer than 3 comparable market sales.",
                "sales": len(comps)}
    ppsf = [p.sale_price / p.sq_ft for p in comps]
    value = median(ppsf) * subject.sq_ft
    ratio = subject.assessment / value
    spread = (max(ppsf) - min(ppsf)) / median(ppsf)
    notes = []
    if ratio > rr["hi"]:
        score_ = "likely"
        if spread > MAX_SPREAD_LIKELY:
            score_ = "possible"
            notes.append("The comparable sales vary widely in price per square foot, so the estimate is uncertain.")
        if renovated:
            score_ = "possible"
            notes.append(RENOVATION_NOTE)
    elif ratio > rr["avg"]:
        score_ = "possible"
        if renovated:
            notes.append(RENOVATION_NOTE)
    else:
        score_ = "unlikely"
    return {"score": score_, "notes": notes, "estimated_value": round(value, -3), "ratio": round(ratio, 4),
            "median_ppsf": round(median(ppsf)), "ppsf_spread": round(spread, 2), "sales": len(comps),
            "size_band": sale_match.size_band, "radius_mi": sale_match.radius_mi,
            "ratio_range": rr,
            "fair_range": [round(subject.assessment / rr["hi"], -3), round(subject.assessment / rr["lo"], -3)]}
