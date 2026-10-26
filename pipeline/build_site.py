"""Build the public site's data: one summary per property, public fields only.

  python pipeline/build_site.py --parcels data/raw/njogis/parcels_hudson.csv            # -> schema `site` in $DATABASE_URL
  python pipeline/build_site.py --parcels ... --db data/portal/bills.sqlite --json-out site/data   # local files

Inputs, all from the store: county records (parcels, parcel_assessments), and, when the crawler has
run, bills (tax history, added assessments, appeal credits). Map positions come from the state parcel
map (fetch_njogis_parcels.py). Without bills, tax history is estimated as assessment x the city's
tax rate and marked so.

Output per property: address, type, size, year built, assessments, tax by year, how its tax change
compares with similar nearby properties and with the city, appeals won nearby, and the appeal screen
with its comparable sales. Owner names, mailing addresses, payments, liens and delinquency are never
read here. In Postgres the output goes to schema `site` (tables site.properties and site.meta), which
the website reads with a read-only role; see docs/hosting.md.
"""
import argparse
import bisect
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import comparables as C  # noqa: E402
from extract_bills import BILL_EXPORT_SQL  # noqa: E402
from store import connect  # noqa: E402

TOWNS = {"0906": "Jersey City"}       # v1: Jersey City only
# general tax rate per $100 of assessed value (NJ GTR history; 2026 from the 2026 bills)
RATES = {"0906": {2019: 1.540, 2020: 1.610, 2021: 1.604, 2022: 2.118, 2023: 2.247, 2024: 2.233,
                  2025: 2.335, 2026: 2.657}}
FIRST_YEAR, LAST_YEAR = 2019, 2026
RENOVATION_YEARS = 5
APPEALS_SINCE = 2022
SHOW_NEIGHBORS = 10
SITE_SCHEMA = "site"


def table_exists(db, name):
    if db.dialect == "sqlite":
        return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())
    return bool(db.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() "
                           "AND table_name = ?", (name,)).fetchone())


def load_positions(path):
    """PAMS_PIN -> (lat, lon) and dwelling counts from the parcel map; condo units fall back to their lot."""
    coord, dwell = {}, {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                coord[r["PAMS_PIN"]] = (float(r["LAT"]), float(r["LON"]))
            except (TypeError, ValueError, KeyError):
                continue
            if (r.get("DWELL") or "").strip().isdigit():
                dwell[r["PAMS_PIN"]] = int(r["DWELL"])
    base = defaultdict(list)
    for pin, c in coord.items():
        base["_".join(pin.split("_")[:3])].append(c)
    base = {k: (sum(c[0] for c in v) / len(v), sum(c[1] for c in v) / len(v)) for k, v in base.items()}
    return coord, base, dwell


def load_properties(db, cd, positions):
    coord, base, dwell = positions
    assess = defaultdict(dict)
    for pin, year, total in db.execute(
            "SELECT pin, year, total FROM parcel_assessments WHERE county_district=? AND record_type='M'", (cd,)):
        assess[pin][int(year)] = total
    exempt = {r[0] for r in db.execute(
        "SELECT pin FROM parcels WHERE county_district=? AND record_type='X'", (cd,))}
    props = {}
    for (pin, loc, cls, q, desc, sq, yb, sd, sp, nu) in db.execute(
            """SELECT pin, property_location, property_class, qualifier, building_desc, sq_ft, year_built,
                      sale_date, sale_price, nu_code FROM parcels WHERE county_district=? AND record_type='M'""", (cd,)):
        bld = "_".join(pin.split("_")[:3])
        c = coord.get(pin) or base.get(bld)
        units = C.units_from(desc, dwell.get(pin) or dwell.get(bld))
        a = assess.get(pin, {})
        latest = a[max(a)] if a else None
        kind = C.kind(cls, q, units)
        if pin in exempt:
            kind = None            # partly exempt (e.g. abated): its tax is not comparable
        props[pin] = C.Prop(pin, (loc or "").strip(), kind, int(sq) if sq else None, int(yb) if yb else None,
                            C.stories_from(desc), C.construction_from(desc), c[0] if c else None,
                            c[1] if c else None, bld, latest, sd, sp, nu,
                            {"desc": desc, "units": units, "class": cls, "qual": q, "assess": a,
                             "abated": pin in exempt})
    return props


def load_taxes(db, cd, props):
    """Tax by year per pin from bills, or estimated from assessments when the crawler has not run."""
    tax, added, credits = defaultdict(dict), defaultdict(set), defaultdict(dict)
    has_bills = table_exists(db, "bills") and db.execute(
        "SELECT 1 FROM bills WHERE county_district=? LIMIT 1", (cd,)).fetchone()
    if has_bills:
        for pin, year, kind, category, amount in db.execute(
                f"""SELECT pin, tax_year, kind, category, SUM(amount) FROM ({BILL_EXPORT_SQL}) b
                    WHERE county_district=? AND tax_year BETWEEN ? AND ? AND category != 'other'
                    GROUP BY pin, tax_year, kind, category""", (cd, FIRST_YEAR, LAST_YEAR + 1)):
            year, amount = int(year), float(amount or 0)
            if category == "property_tax" and year <= LAST_YEAR:
                tax[pin][year] = tax[pin].get(year, 0) + amount
            if kind == "added" and amount > 0:
                added[pin].add(year)
            if category == "appeal_adjustment" and amount < -1:
                credits[pin][year] = credits[pin].get(year, 0) + amount
        return tax, added, credits, "bills"
    rates = RATES[cd]
    for pin, p in props.items():
        for year, total in p.extra["assess"].items():
            if year in rates and total:
                tax[pin][year] = total * rates[year] / 100
    return tax, added, credits, "estimated"


def change(taxes, base_year, last_year=LAST_YEAR):
    a, b = taxes.get(base_year), taxes.get(last_year)
    return (b / a - 1) if a and b and a > 0 else None


def percentile(sorted_values, v):
    """Share of the group with a smaller change, counting ties as half (many homes share the city-wide rate change)."""
    if v is None or not sorted_values:
        return None
    lo, hi = bisect.bisect_left(sorted_values, v), bisect.bisect_right(sorted_values, v)
    return round(100 * (lo + (hi - lo) / 2) / len(sorted_values))


def r0(x):
    return None if x is None else round(x)


def build(db, cd, positions, today=None):
    today = today or date.today()
    props = load_properties(db, cd, positions)
    tax, added, credits, source = load_taxes(db, cd, props)
    base_year = FIRST_YEAR if source == "bills" else min(RATES[cd])
    base_year = max(base_year, 2023) if source == "estimated" else base_year
    index = C.Index(props.values())

    # citywide distribution of tax change, by type and era
    groups = defaultdict(list)
    for pin, p in props.items():
        ch = change(tax.get(pin, {}), base_year)
        if p.kind and ch is not None:
            groups[(p.kind, p.era)].append(ch)
    for g in groups.values():
        g.sort()

    renovated_since = today.year - RENOVATION_YEARS
    out = {}
    for pin, p in props.items():
        t = tax.get(pin, {})
        your_change = change(t, base_year)
        rec = {
            "pin": pin, "town": TOWNS[cd], "address": p.address, "unit": p.extra["qual"] or None,
            "kind": p.kind, "class": p.extra["class"], "sq_ft": p.sq_ft, "year_built": p.year_built,
            "building": p.extra["desc"], "lat": p.lat, "lon": p.lon, "abated": p.extra["abated"],
            "assessment": {str(y): r0(v) for y, v in sorted(p.extra["assess"].items())},
            "tax": {str(y): r0(v) for y, v in sorted(t.items())}, "tax_source": source, "base_year": base_year,
            "added_assessment_years": sorted(added.get(pin, ())),
            "appeal_credits": {str(y): r0(v) for y, v in sorted(credits.get(pin, {}).items())},
            "change": None if your_change is None else round(your_change, 4),
        }
        if p.kind and p.lat is not None and p.usable_size:
            m = C.neighbors(index, p)
            nb = [(q, d) for q, d, _ in m.props]
            changes = [c for c in (change(tax.get(q.pin, {}), base_year) for q, _ in nb) if c is not None]
            by_year = {}
            for y in range(base_year, LAST_YEAR + 1):
                vals = [tax[q.pin][y] for q, _ in nb if y in tax.get(q.pin, {})]
                by_year[str(y)] = r0(C.median(vals)) if len(vals) >= 3 else None
            won = [q for q, _ in nb if any(int(y) >= APPEALS_SINCE for y in credits.get(q.pin, {}))]
            reductions = []
            for q in won:
                for y, v in credits[q.pin].items():
                    if y >= APPEALS_SINCE and tax.get(q.pin, {}).get(y):
                        reductions.append(-v / tax[q.pin][y])
            group = groups.get((p.kind, p.era), [])
            rec["compare"] = {
                "count": len(nb), "size_band": m.size_band, "radius_mi": m.radius_mi, "reason": m.reason or None,
                "median_change": None if not changes else round(C.median(changes), 4),
                "median_tax_by_year": by_year,
                "city_percentile": percentile(group, your_change), "city_group_size": len(group),
                "list": [{"pin": q.pin, "address": q.address, "unit": q.extra["qual"] or None, "sq_ft": q.sq_ft,
                          "year_built": q.year_built, "miles": round(d, 2),
                          "lat": round(q.lat, 6), "lon": round(q.lon, 6),
                          "change": None if change(tax.get(q.pin, {}), base_year) is None
                          else round(change(tax.get(q.pin, {}), base_year), 4)} for q, d in nb[:SHOW_NEIGHBORS]],
            }
            rec["appeals_nearby"] = {"since": APPEALS_SINCE, "compared": len(nb), "won": len(won),
                                     "median_reduction": None if not reductions else round(C.median(reductions), 4)}
            sm = C.sales(index, p)
            renovated = any(y >= renovated_since for y in added.get(pin, ()))
            result = C.appeal(p, sm, renovated=renovated)
            result["comparable_sales"] = [
                {"pin": q.pin, "address": q.address, "unit": q.extra["qual"] or None, "sq_ft": q.sq_ft,
                 "year_built": q.year_built, "lat": round(q.lat, 6), "lon": round(q.lon, 6),
                 "sale_date": q.sale_date, "price": r0(q.sale_price), "ppsf": r0(q.sale_price / q.sq_ft),
                 "miles": round(d, 2)} for q, d, _ in sm.props]
            rec["appeal"] = result
        else:
            reason = ("Partly exempt (for example an abatement), so it is not compared." if p.extra["abated"]
                      else "This property type is not compared in this version." if not p.kind
                      else "No usable floor area or map position for this property.")
            rec["compare"] = {"count": 0, "reason": reason}
            rec["appeal"] = {"score": "not_applicable", "reason": reason}
        out[pin] = rec
    meta = {"town": TOWNS[cd], "county_district": cd, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tax_source": source, "base_year": base_year, "last_year": LAST_YEAR, "ratio_year": C.RATIO_YEAR,
            "ratio": C.RATIOS[cd], "valuation_date": C.VALUATION_DATE.isoformat(), "properties": len(out),
            "data_as_of": db.execute("SELECT MAX(data_as_of) FROM parcels WHERE county_district=?", (cd,)).fetchone()[0]}
    return out, meta


def summary_row(rec):
    """The fields the map and search need, in a fixed order."""
    t = rec["tax"]
    latest = t.get(str(LAST_YEAR))
    return [rec["pin"], rec["address"], rec["unit"], rec["kind"],
            None if rec["lat"] is None else round(rec["lat"], 6), None if rec["lon"] is None else round(rec["lon"], 6),
            latest, rec["change"], (rec.get("appeal") or {}).get("score")]


SUMMARY_FIELDS = ["pin", "address", "unit", "kind", "lat", "lon", "tax", "change", "appeal"]


def write_json(out, meta, dest):
    dest = Path(dest)
    (dest / "p").mkdir(parents=True, exist_ok=True)
    for old in (dest / "p").glob("*.json"):
        old.unlink()
    shards = defaultdict(dict)
    for pin, rec in out.items():
        shards[shard_of(pin)][pin] = rec
    for k, recs in shards.items():
        (dest / "p" / f"{k}.json").write_text(json.dumps(recs, separators=(",", ":")))
    rows = [summary_row(r) for r in out.values()]
    (dest / "index.json").write_text(json.dumps({"fields": SUMMARY_FIELDS, "rows": rows}, separators=(",", ":")))
    (dest / "meta.json").write_text(json.dumps(meta, indent=1))


def shard_of(pin, n=64):
    h = 0
    for ch in pin:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h % n


def write_postgres(db, out, meta):
    """Replace site.properties and site.meta in one transaction, so the site never sees a half-built table."""
    db.execute(f"CREATE SCHEMA IF NOT EXISTS {SITE_SCHEMA}")
    db.execute(f"""CREATE TABLE IF NOT EXISTS {SITE_SCHEMA}.properties (
        pin TEXT PRIMARY KEY, town TEXT, address TEXT, unit TEXT, kind TEXT, lat DOUBLE PRECISION,
        lon DOUBLE PRECISION, tax DOUBLE PRECISION, change DOUBLE PRECISION, appeal TEXT, data JSONB)""")
    db.execute(f"CREATE TABLE IF NOT EXISTS {SITE_SCHEMA}.meta (key TEXT PRIMARY KEY, value JSONB)")
    for role in ("anon", "authenticated"):
        if db.execute("SELECT 1 FROM pg_roles WHERE rolname = ?", (role,)).fetchone():
            db.execute(f"REVOKE ALL ON SCHEMA {SITE_SCHEMA} FROM {role}")
            db.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SITE_SCHEMA} FROM {role}")
    db.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    db.execute(f"CREATE INDEX IF NOT EXISTS properties_address_trgm ON {SITE_SCHEMA}.properties "
               "USING gin (address gin_trgm_ops)")
    db.execute(f"DELETE FROM {SITE_SCHEMA}.properties WHERE town = ?", (meta["town"],))
    rows = [(*summary_row(r)[:8], summary_row(r)[8], json.dumps(r, separators=(",", ":"))) for r in out.values()]
    rows = [(r[0], meta["town"], *r[1:]) for r in rows]
    db.executemany(f"""INSERT INTO {SITE_SCHEMA}.properties
                       (pin, town, address, unit, kind, lat, lon, tax, change, appeal, data)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""", rows)
    db.execute(f"""INSERT INTO {SITE_SCHEMA}.meta VALUES (?, ?)
                   ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
               (meta["county_district"], json.dumps(meta)))
    db.commit()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("DATABASE_URL") or "data/portal/bills.sqlite")
    ap.add_argument("--parcels", required=True, help="parcels_hudson.csv from fetch_njogis_parcels.py")
    ap.add_argument("--json-out", help="write JSON files here instead of the database's site schema")
    args = ap.parse_args(argv)
    db = connect(args.db)
    positions = load_positions(args.parcels)
    for cd in TOWNS:
        out, meta = build(db, cd, positions)
        if args.json_out:
            write_json(out, meta, args.json_out)
        elif db.dialect == "postgres":
            write_postgres(db, out, meta)
        else:
            sys.exit("--json-out is required with a SQLite store")
        scored = defaultdict(int)
        for r in out.values():
            scored[(r.get("appeal") or {}).get("score")] += 1
        print(f"{meta['town']}: {len(out):,} properties, tax from {meta['tax_source']}; appeal screen: "
              + ", ".join(f"{k}: {v:,}" for k, v in sorted(scored.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
