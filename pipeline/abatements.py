"""Tax abatements, condo buildings and citywide totals, from the county tax board records.

Abatements. New Jersey towns can exempt a building from regular tax for a set term; the owner pays
a negotiated annual charge instead (a PILOT). The county records show this two ways:
  - partly abated (most condo units): the taxable record (M) holds the land, a second record (X,
    class 15F) holds the exempt building value;
  - fully abated (whole projects): the only record is class 15F, carrying an abatement statute.
Either way the record names the statute and the exemption's start and end dates (MMDDYY).
  N.J.S.A. 40A:20  Long Term Tax Exemption Law (up to 30 years)
  N.J.S.A. 40A:21  Five-Year Exemption and Abatement Law (yet Jersey City's run 20-30 years, so the
                   site labels them by statute, not as "five-year")
  N.J.S.A. 55:14K, 55:16  affordable-housing exemptions;  40:55C  older urban renewal law
Other class 15 statutes (public, religious, charitable property) are exemptions, not abatements.

An abatement that ended shows in the assessment history: the taxable record held only land (building
$0) for a building that already existed, then the building value appears.
"""
import re
from datetime import date

LAWS = [("long_term", r"\b40A?:\s*20"), ("five_year", r"\b4[06]A:\s*21"), ("affordable", r"\b55:\s*(14K|16)"),
        ("urban_renewal", r"\b40:\s*55C")]
LAW_CODE = {None: 0, "long_term": 1, "five_year": 2, "affordable": 3, "urban_renewal": 3, "other": 3, "ended": 4}


def law_of(statute):
    for name, pattern in LAWS:
        if re.search(pattern, statute or ""):
            return name
    return None


def mmddyy(s):
    """'062409' -> '2009-06-24'; anything else -> None."""
    m = re.fullmatch(r"\s*(\d\d)(\d\d)(\d\d)\s*", s or "")
    if not m:
        return None
    mm, dd, yy = (int(g) for g in m.groups())
    try:
        return date(2000 + yy if yy < 70 else 1900 + yy, mm, dd).isoformat()
    except ValueError:
        return None


def active(statute, init, further, exempt_value, full):
    """The abatement record for a property that is exempt today, or None if it is not an abatement."""
    law = law_of(statute)
    if law is None and full:
        return None                    # fully exempt public / charitable property: not an abatement
    return {"status": "active", "law": law or "other", "statute": (statute or "").strip() or None,
            "since": mmddyy(init), "until": mmddyy(further), "full": full,
            "exempt_value": round(exempt_value) if exempt_value else None}


def ended_year(history, year_built):
    """history: {year: (land, building)} of the taxable record. The year the building value came onto
    the roll for a building that already stood (so an exemption ended), or None."""
    years = sorted(history)
    for a, b in zip(years, years[1:]):
        (land_a, bld_a), (_, bld_b) = history[a], history[b]
        if not bld_a and land_a and bld_b and year_built and year_built < a:
            return b
    return None


# --- condo buildings -----------------------------------------------------------------------------

def floor_of(unit):
    """C1201 -> 12, C0310 -> 3; units without a floor number (C0010, C003L, C0PHG) -> None."""
    m = re.fullmatch(r"C0*([1-9]\d{2,3})", unit or "")
    return int(m.group(1)[:-2]) if m else None


def _fit(points):
    """y = a + b x, robust to the few over- or under-assessed units we are looking for (Theil-Sen:
    the median of the pairwise slopes, then the median intercept)."""
    slopes = [(y2 - y1) / (x2 - x1) for i, (x1, y1) in enumerate(points) for x2, y2 in points[i + 1:] if x2 != x1]
    b = median(slopes) or 0.0
    return median([y - b * x for x, y in points]), b


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


ABOVE = 0.10        # assessed this much above comparable units in the building: worth a look
SHOW_UNITS = 12


def buildings(units):
    """units: [{pin, unit, sq_ft, value, abated}], every unit of one building (value = full assessment,
    taxable plus abated). Returns {pin: building summary} for units with a usable size and value."""
    ok = [u for u in units if u["sq_ft"] and u["value"]]
    if len(ok) < 3:
        return {}
    for u in ok:
        u["ppsf"] = u["value"] / u["sq_ft"]
        u["floor"] = floor_of(u["unit"])
    med = median([u["ppsf"] for u in ok])
    with_floor = [(u["floor"], u["ppsf"]) for u in ok if u["floor"] is not None]
    fit = _fit(with_floor) if len(with_floor) >= 8 and len({f for f, _ in with_floor}) >= 3 else None
    out = {}
    for u in ok:
        expected = fit[0] + fit[1] * u["floor"] if fit and u["floor"] is not None else None
        vs_floor = u["ppsf"] / expected - 1 if expected and expected > 0 else None
        vs_median = u["ppsf"] / med - 1
        others = sorted((o for o in ok if o is not u),
                        key=lambda o: (abs((o["floor"] or 0) - (u["floor"] or 0)) if u["floor"] is not None else 0)
                        + abs(o["sq_ft"] - u["sq_ft"]) / u["sq_ft"] * 10)
        out[u["pin"]] = {
            "units": len(units), "compared": len(ok), "abated_units": sum(1 for o in units if o["abated"]),
            "median_ppsf": round(med), "ppsf": round(u["ppsf"]), "value": round(u["value"]), "floor": u["floor"],
            "vs_median": round(vs_median, 4), "vs_floor": None if vs_floor is None else round(vs_floor, 4),
            "above": (vs_floor if vs_floor is not None else vs_median) > ABOVE,
            "higher_than": round(100 * (sum(1 for o in ok if o["ppsf"] < u["ppsf"])        # ties count half
                                        + sum(1 for o in ok if o["ppsf"] == u["ppsf"] and o is not u) / 2) / len(ok)),
            "list": [{"pin": o["pin"], "unit": o["unit"], "floor": o["floor"], "sq_ft": o["sq_ft"],
                      "value": round(o["value"]), "ppsf": round(o["ppsf"])} for o in others[:SHOW_UNITS]],
        }
    return out


# --- citywide totals -----------------------------------------------------------------------------

CLASS_GROUPS = [("Homes and condos", ("2",)), ("Commercial", ("4A",)), ("Apartment buildings", ("4C",)),
                ("Industrial", ("4B",)), ("Vacant land", ("1",))]


def city_stats(rows, rate, today=None):
    """rows: one per taxable-roll record: {class, value, abatement (dict or None), ended (year or None),
    unit (bool), lot}. value = latest assessment of the record (the taxable part for partly abated)."""
    today = today or date.today()
    taxable = sum(r["value"] or 0 for r in rows if not r["class"].startswith("15"))
    exempt = sum(r["value"] or 0 for r in rows if r["class"].startswith("15") and not r["abatement"])
    groups = []
    for label, classes in CLASS_GROUPS:
        v = sum(r["value"] or 0 for r in rows if r["class"] in classes)
        groups.append({"label": label, "value": round(v), "share": round(v / taxable, 4) if taxable else None})
    other = taxable - sum(g["value"] for g in groups)
    if other > 0:
        groups.append({"label": "Other", "value": round(other), "share": round(other / taxable, 4)})
    ab = [r["abatement"] for r in rows if r["abatement"]]
    ab_value = sum(a["exempt_value"] or 0 for a in ab)
    horizon = f"{today.year + 4}-12-31"
    by_law = {}
    for a in ab:
        by_law[a["law"]] = by_law.get(a["law"], 0) + 1
    return {
        "taxable_value": round(taxable), "levy_estimate": round(taxable * rate / 100), "rate": rate,
        "records": len(rows), "exempt_value": round(exempt), "by_class": groups,
        "abatement": {
            "properties": len(ab), "units": sum(1 for r in rows if r["abatement"] and r["unit"]),
            "buildings": len({r["lot"] for r in rows if r["abatement"]}),
            "full": sum(1 for a in ab if a["full"]), "value": round(ab_value),
            "share_of_value": round(ab_value / (taxable + ab_value), 4) if taxable + ab_value else None,
            "regular_tax_equivalent": round(ab_value * rate / 100), "by_law": by_law,
            "ending_by": today.year + 4,
            "ending_soon": sum(1 for a in ab if a["until"] and today.isoformat() <= a["until"] <= horizon),
            "ended_recently": sum(1 for r in rows if r["ended"] and r["ended"] >= today.year - 2),
            "ended_since": today.year - 2,
        },
    }
