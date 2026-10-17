"""Extract quarterly tax bills from city billing portals into a resumable SQLite store.

  python pipeline/extract_bills.py index  --town jersey-city            # list every account
  python pipeline/extract_bills.py fetch  --town jersey-city --limit 500 # fetch bills for pending accounts
  python pipeline/extract_bills.py status
  python pipeline/extract_bills.py export --out data/portal/export

Both stages are resumable: stop any time (Ctrl-C) and re-run the same command.
Requests are sequential with --interval seconds between them (default 1.0).
Owner names / mailing addresses are never stored.
"""
import argparse
import csv
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from portals.http import PoliteSession  # noqa: E402
from portals.registry import TOWNS, portal_for  # noqa: E402

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "portal" / "bills.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  county_district TEXT, account_id TEXT, pin TEXT, property_location TEXT, property_class TEXT,
  land_value REAL, improvement_value REAL, net_taxable REAL,
  status TEXT DEFAULT 'pending', error TEXT, fetched_at TEXT,
  PRIMARY KEY (county_district, account_id)
);
CREATE INDEX IF NOT EXISTS accounts_pin ON accounts(pin);
CREATE INDEX IF NOT EXISTS accounts_status ON accounts(county_district, status);
CREATE TABLE IF NOT EXISTS bills (
  county_district TEXT, account_id TEXT, pin TEXT, tax_year INTEGER, quarter INTEGER,
  due_date TEXT, kind TEXT, category TEXT, amount REAL, source TEXT, fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS bills_acct ON bills(county_district, account_id);
CREATE INDEX IF NOT EXISTS bills_pin ON bills(pin, tax_year);
CREATE TABLE IF NOT EXISTS index_progress (
  county_district TEXT PRIMARY KEY, cursor TEXT, complete INTEGER DEFAULT 0, updated_at TEXT
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def cmd_index(db, args):
    town = TOWNS[args.town]
    cd = town["county_district"]
    portal = portal_for(args.town, PoliteSession(min_interval=args.interval))
    row = db.execute("SELECT cursor, complete FROM index_progress WHERE county_district=?", (cd,)).fetchone()
    if row and row[1] and not args.restart:
        print(f"{town['name']}: index already complete (use --restart to rebuild)")
        return
    cursor = None if (args.restart or not row) else row[0]
    if args.start:
        cursor = args.start
    if cursor is None:
        accounts = portal.iter_accounts(max_pages=args.max_pages)
    elif hasattr(portal, "wippid"):
        accounts = portal.iter_accounts(start_key=cursor, max_pages=args.max_pages)
    else:
        accounts = portal.iter_accounts(start_page=int(cursor), max_pages=args.max_pages)

    n, last_cursor = 0, cursor
    for cur, acct in accounts:
        db.execute(
            """INSERT INTO accounts (county_district, account_id, pin, property_location, property_class)
               VALUES (?,?,?,?,?)
               ON CONFLICT(county_district, account_id) DO UPDATE SET
                 pin=excluded.pin, property_location=excluded.property_location""",
            (cd, acct.account_id, acct.pin, acct.property_location, acct.property_class),
        )
        n += 1
        if cur != last_cursor:
            db.execute("INSERT OR REPLACE INTO index_progress VALUES (?,?,0,?)", (cd, str(cur), now()))
            db.commit()
            last_cursor = cur
            print(f"{town['name']}: {n} accounts indexed (cursor {str(cur).strip() or 'start'})", flush=True)
    complete = 0 if args.max_pages else 1
    db.execute("INSERT OR REPLACE INTO index_progress VALUES (?,?,?,?)", (cd, str(last_cursor), complete, now()))
    db.commit()
    print(f"{town['name']}: done, {n} accounts this run, complete={bool(complete)}")


def cmd_fetch(db, args):
    from portals.models import Account

    town = TOWNS[args.town]
    cd = town["county_district"]
    portal = portal_for(args.town, PoliteSession(min_interval=args.interval))
    statuses = ("pending", "error") if args.retry_errors else ("pending",)
    q = f"""SELECT account_id, pin, property_location, property_class FROM accounts
            WHERE county_district=? AND status IN ({','.join('?' * len(statuses))}) ORDER BY rowid"""
    params = [cd, *statuses]
    if args.limit:
        q += " LIMIT ?"
        params.append(args.limit)
    todo = db.execute(q, params).fetchall()
    print(f"{town['name']}: {len(todo)} accounts to fetch")
    for i, (account_id, pin, loc, cls) in enumerate(todo, 1):
        acct = Account(cd, account_id, pin, loc, cls or "")
        try:
            res = portal.fetch(acct)
        except Exception as e:  # keep crawling; record and move on
            db.execute("UPDATE accounts SET status='error', error=?, fetched_at=? WHERE county_district=? AND account_id=?",
                       (str(e)[:500], now(), cd, account_id))
            db.commit()
            print(f"  {i}/{len(todo)} {pin} ERROR {e}", flush=True)
            continue
        a, ts = res.account, now()
        db.execute("DELETE FROM bills WHERE county_district=? AND account_id=?", (cd, account_id))
        db.executemany(
            "INSERT INTO bills VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(cd, b.account_id, b.pin, b.tax_year, b.quarter, b.due_date, b.kind, b.category, b.amount, b.source, ts)
             for b in res.bills],
        )
        db.execute(
            """UPDATE accounts SET pin=?, property_class=?, land_value=?, improvement_value=?, net_taxable=?,
               status=?, error=NULL, fetched_at=? WHERE county_district=? AND account_id=?""",
            (a.pin, a.property_class, a.land_value, a.improvement_value, a.net_taxable, a.status, ts, cd, account_id),
        )
        db.commit()
        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} fetched ({portal.http.requests_made} requests)", flush=True)


def cmd_status(db, args):
    print(f"{'town':<12} {'indexed':>8} {'done':>7} {'no_bills':>8} {'pending':>8} {'error':>6} {'bills':>9}  index")
    for slug, t in TOWNS.items():
        cd = t["county_district"]
        counts = dict(db.execute("SELECT status, COUNT(*) FROM accounts WHERE county_district=? GROUP BY status", (cd,)).fetchall())
        nb = db.execute("SELECT COUNT(*) FROM bills WHERE county_district=?", (cd,)).fetchone()[0]
        prog = db.execute("SELECT complete FROM index_progress WHERE county_district=?", (cd,)).fetchone()
        idx = "complete" if prog and prog[0] else ("partial" if prog else "-")
        print(f"{slug:<12} {sum(counts.values()):>8} {counts.get('done', 0):>7} {counts.get('no_bills', 0):>8} "
              f"{counts.get('pending', 0):>8} {counts.get('error', 0):>6} {nb:>9}  {idx}")


def cmd_export(db, args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for table, order in (("accounts", "county_district, pin"), ("bills", "county_district, pin, due_date")):
        cur = db.execute(f"SELECT * FROM {table} ORDER BY {order}")
        cols = [c[0] for c in cur.description]
        with open(out / f"{table}.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows(cur)
    # Annual totals per parcel, the main input for the app
    cur = db.execute("""
        SELECT county_district, pin, tax_year,
               ROUND(SUM(CASE WHEN kind='tax' THEN amount ELSE 0 END), 2) AS regular_tax,
               ROUND(SUM(CASE WHEN category='property_tax' THEN amount ELSE 0 END), 2) AS property_tax_billed,
               ROUND(SUM(CASE WHEN category='appeal_adjustment' THEN amount ELSE 0 END), 2) AS appeal_adjustments,
               ROUND(SUM(CASE WHEN kind='tax' AND quarter IN (1,2) THEN amount ELSE 0 END), 2) AS h1_tax,
               ROUND(SUM(CASE WHEN kind='tax' AND quarter IN (3,4) THEN amount ELSE 0 END), 2) AS h2_tax,
               COUNT(DISTINCT CASE WHEN kind='tax' THEN quarter END) AS quarters
        FROM bills WHERE category != 'other'
        GROUP BY county_district, pin, tax_year ORDER BY county_district, pin, tax_year""")
    cols = [c[0] for c in cur.description]
    with open(out / "annual.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(cur)
    print(f"exported accounts.csv, bills.csv, annual.csv to {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("index", "fetch"):
        p = sub.add_parser(name)
        p.add_argument("--town", required=True, choices=TOWNS)
        p.add_argument("--interval", type=float, default=1.0, help="seconds between requests")
        if name == "index":
            p.add_argument("--max-pages", type=int, help="stop after N pages (for pilots)")
            p.add_argument("--restart", action="store_true")
            p.add_argument("--start", help="start at this page (HLS) or block/lot key (WIPP)")
        else:
            p.add_argument("--limit", type=int)
            p.add_argument("--retry-errors", action="store_true")
    sub.add_parser("status")
    p = sub.add_parser("export")
    p.add_argument("--out", default="data/portal/export")
    args = ap.parse_args(argv)
    db = connect(args.db)
    {"index": cmd_index, "fetch": cmd_fetch, "status": cmd_status, "export": cmd_export}[args.cmd](db, args)


if __name__ == "__main__":
    main()
