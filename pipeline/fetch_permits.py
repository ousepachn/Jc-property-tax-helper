"""Load Jersey City's construction permits (the city's EnerGov permit portal) into the store.

  python pipeline/fetch_permits.py recent                 # permits issued in the last --days (default 45)
  python pipeline/fetch_permits.py backfill --max-minutes 300   # every building's history, resumable
  python pipeline/fetch_permits.py status

The portal returns at most 10,000 results per search and ignores its own date filters, so:
- `recent` reads the newest permits first, 500 a page, until it passes --days back. Run daily.
- `backfill` searches once per building address from the county records (`parcels`), which returns
  that building's whole history, every condo unit included, and keeps the permits whose parcel is
  that tax lot. About 40,000 searches, one a second: several runs; each continues where the last
  stopped. Afterwards it re-reads buildings older than --refresh-days, which picks up status
  changes (finished, certificate of occupancy) on older permits.

Tables (private store, like everything else; build_site.py publishes a summary per property):
  permits          one row per permit: parcel pin, type, status, dates, work description, category
  permit_searches  one row per street address searched, with when and how many permits it kept
Permits carry no applicant or contractor names, and none are stored.
"""
import argparse
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from portals.energov import EnerGov  # noqa: E402
from store import connect, lock_down  # noqa: E402

CD = "0906"     # the EnerGov portal is Jersey City's
SCHEMA = """
CREATE TABLE IF NOT EXISTS permits (
  county_district TEXT, permit_no TEXT, case_id TEXT, pin TEXT, lot TEXT, address TEXT, case_type TEXT,
  work_class TEXT, category TEXT, status TEXT, apply_date TEXT, issue_date TEXT, final_date TEXT,
  expire_date TEXT, description TEXT, fetched_at TEXT,
  PRIMARY KEY (county_district, permit_no)
);
CREATE INDEX IF NOT EXISTS permits_lot ON permits(county_district, lot);
CREATE TABLE IF NOT EXISTS permit_searches (
  county_district TEXT, address TEXT, fetched_at TEXT, found INTEGER,
  PRIMARY KEY (county_district, address)
);
"""
TABLES = ("permits", "permit_searches")
COLUMNS = ("county_district", "permit_no", "case_id", "pin", "lot", "address", "case_type", "work_class",
           "category", "status", "apply_date", "issue_date", "final_date", "expire_date", "description", "fetched_at")

# What the work usually means for the assessment. Order matters: first match wins.
CATEGORIES = [
    ("utility", r"\bMUA\b|development fee|hydrant"),
    ("certificate", r"certificate|\bC\.?O\b"),
    ("new_construction", r"new construction"),
    ("addition", r"addition"),
    ("demolition", r"complete demolition|building demo"),
    ("renovation", r"alteration|renovation|interior demo|change of use"),
    ("trade", r"subcode technical section(?! - minor)"),
    ("minor", r"minor work|hot water|furnace|boiler|air condition|roof|oil tank|amp service|ev charger|solar|"
              r"sprinkler|fire alarm|water service|elevator"),
]
MAJOR = ("new_construction", "addition", "renovation", "demolition")


# Work that adds space, units or finish usually raises the assessment; like-for-like replacement and
# repairs usually don't. Read from the free-text description, so it's a hint, not a finding.
EXPANDS = re.compile(r"\b(addition|extension|dormer|new (story|floor|unit|bath|kitchen)|add(s|ed|ing)?\b[\w ]{0,20}?\b"
                     r"(story|stories|floor|unit|units|bedroom|bathroom|bath|deck)|finish(ed|ing)? (the )?(basement|attic)|"
                     r"conver(t|sion)|gut|full renovation|complete renovation|legaliz|duplex|rooftop|penthouse|"
                     r"new construction|erect|build (a )?new)\b", re.I)
REPAIR = re.compile(r"\b(replace|replacement|repair|in[- ]kind|like for like|same location|maintenance|patch|"
                    r"water heater|boiler|furnace|oil tank|smoke|fire alarm|sprinkler|service upgrade|meter)\b", re.I)
DONE = re.compile(r"complete|closed|final|co issued|certificate issued", re.I)


def tax_relevance(category, description=""):
    """likely / possible / unlikely to change the assessment, or 'lower' (demolition)."""
    d = description or ""
    if category in ("new_construction", "addition"):
        return "likely"
    if category == "demolition":
        return "lower"
    if category == "renovation":
        if EXPANDS.search(d):
            return "likely"
        return "unlikely" if REPAIR.search(d) else "possible"
    return "unlikely"


def category(case_type, work_class=""):
    text = f"{case_type} {work_class}"
    for name, pattern in CATEGORIES:
        if re.search(pattern, text, re.I):
            return name
    return "other"


def lot_of(pin):
    """0906_16104_24_C0302 -> 0906_16104_24 (condo units share their building's lot)."""
    return "_".join(pin.split("_")[:3]) if pin else None


def normalize_pin(pin):
    if not pin:
        return None
    parts = pin.strip().split("_")
    return "_".join(parts[:3] + [p.upper() for p in parts[3:]])


def search_address(location):
    """The county's '66 GAUTIER AVE.' -> '66 GAUTIER AVE'; a range '100-102 X ST' -> '100 X ST'."""
    a = re.sub(r"[.,#]", " ", location or "").upper()
    a = re.sub(r"^(\d+[A-Z]?)\s*-\s*\d+[A-Z]?\b", r"\1", a.strip())
    return " ".join(a.split())


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert(db, rows, fetched_at):
    recs = []
    for r in rows:
        pin = normalize_pin(r["pin"])
        recs.append((CD, r["permit_no"], r["case_id"], pin, lot_of(pin), r["address"], r["case_type"], r["work_class"],
                     category(r["case_type"], r["work_class"]), r["status"], r["apply_date"], r["issue_date"],
                     r["final_date"], r["expire_date"], r["description"], fetched_at))
    if not recs:
        return 0
    cols = ", ".join(COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in COLUMNS[2:])
    db.executemany(f"""INSERT INTO permits ({cols}) VALUES ({', '.join('?' * len(COLUMNS))})
                       ON CONFLICT (county_district, permit_no) DO UPDATE SET {updates}""", recs)
    return len(recs)


def recent(db, portal, days, today=None):
    """Newest permits first, until a page is entirely older than `days` (pages hold 500)."""
    cutoff = ((today or date.today()) - timedelta(days=days)).isoformat()
    total, page, pages = 0, 1, None
    while pages is None or page <= min(pages, 20):              # 20 x 500 = the portal's 10,000 limit
        rows, pages = portal.permits_page(page, page_size=500)
        total += upsert(db, rows, now())
        db.commit()
        issued = [r["issue_date"] for r in rows if r["issue_date"]]
        if not rows or (issued and max(issued) < cutoff):
            break
        page += 1
    return total


def pending_searches(db, refresh_days):
    """[(address, {lots at it})]: addresses not yet searched, then those searched more than refresh_days ago."""
    stale = (datetime.now(timezone.utc) - timedelta(days=refresh_days)).isoformat(timespec="seconds")
    done = dict(db.execute("SELECT address, fetched_at FROM permit_searches WHERE county_district = ?", (CD,)).fetchall())
    lots = defaultdict(set)
    for pin, loc in db.execute("SELECT pin, property_location FROM parcels WHERE county_district = ?", (CD,)):
        a = search_address(loc)
        if a and re.match(r"\d", a):
            lots[a].add(lot_of(pin))
    new = sorted(a for a in lots if a not in done)
    old = sorted((a for a in lots if a in done and done[a] < stale), key=lambda a: done[a])
    return [(a, lots[a]) for a in new + old]


def backfill(db, portal, max_minutes=None, refresh_days=120, log=print):
    deadline = time.monotonic() + max_minutes * 60 if max_minutes else None
    todo = pending_searches(db, refresh_days)
    log(f"{len(todo):,} street addresses to search")
    searched = stored = 0
    for address, lots in todo:
        if deadline and time.monotonic() > deadline:
            break
        rows = [r for r in portal.permits_for(address) if lot_of(normalize_pin(r["pin"])) in lots]
        stamp = now()
        stored += upsert(db, rows, stamp)
        db.execute("""INSERT INTO permit_searches (county_district, address, fetched_at, found) VALUES (?,?,?,?)
                      ON CONFLICT (county_district, address) DO UPDATE SET fetched_at = excluded.fetched_at,
                      found = excluded.found""", (CD, address, stamp, len(rows)))
        db.commit()
        searched += 1
        if searched % 500 == 0:
            log(f"  {searched:,} searched, {stored:,} permits stored")
    return searched, stored, len(todo) - searched


def status(db):
    n = db.execute("SELECT COUNT(*) FROM permits WHERE county_district = ?", (CD,)).fetchone()[0]
    s = db.execute("SELECT COUNT(*), MIN(fetched_at), MAX(fetched_at) FROM permit_searches WHERE county_district = ?",
                   (CD,)).fetchone()
    by = db.execute("SELECT category, COUNT(*) FROM permits WHERE county_district = ? GROUP BY category ORDER BY 2 DESC",
                    (CD,)).fetchall()
    newest = db.execute("SELECT MAX(issue_date) FROM permits WHERE county_district = ?", (CD,)).fetchone()[0]
    return {"permits": n, "addresses_searched": s[0], "oldest_search": s[1], "newest_search": s[2],
            "newest_issue_date": newest, "by_category": dict(by)}


def open_db(target):
    db = connect(target)
    db.schema_lock()
    db.executescript(SCHEMA)
    lock_down(db, TABLES)
    db.commit()
    return db


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("recent", "backfill", "status"))
    ap.add_argument("--db", default=os.environ.get("DATABASE_URL") or "data/portal/bills.sqlite")
    ap.add_argument("--days", type=int, default=45, help="recent: how far back to read")
    ap.add_argument("--max-minutes", type=float, help="backfill: stop after this long")
    ap.add_argument("--refresh-days", type=int, default=120, help="backfill: re-search buildings older than this")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between requests")
    args = ap.parse_args(argv)
    db = open_db(args.db)
    if args.command == "status":
        for k, v in status(db).items():
            print(f"{k}: {v}")
        return
    from portals.http import PoliteSession
    portal = EnerGov(PoliteSession(min_interval=args.interval, timeout=120))
    if args.command == "recent":
        print(f"recent: {recent(db, portal, args.days):,} permits stored or updated")
    else:
        searched, stored, left = backfill(db, portal, args.max_minutes, args.refresh_days)
        print(f"backfill: {searched:,} addresses searched, {stored:,} permits stored, {left:,} left")
    print(status(db))


if __name__ == "__main__":
    main()
