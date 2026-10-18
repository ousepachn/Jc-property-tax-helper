"""Extract quarterly tax bills from city billing portals into a resumable SQLite store.

  python pipeline/extract_bills.py index  --town jersey-city            # list every account
  python pipeline/extract_bills.py fetch  --town jersey-city --limit 500 # fetch bills for pending accounts
  python pipeline/extract_bills.py rederive --town jersey-city         # re-parse stored raw responses (no network)
  python pipeline/extract_bills.py status
  python pipeline/extract_bills.py export --out data/portal/export

Both stages are resumable: stop any time (Ctrl-C) and re-run the same command.
Requests are sequential with --interval seconds between them (default 1.0).

Owner names and mailing addresses are stored only with --include-owners, and never for accounts
the portal flags under Daniel's Law. --keep-raw also stores each portal response (zlib) so nothing
is lost; raw responses are kept only together with --include-owners, since they contain names.
"""
import argparse
import csv
import json
import sqlite3
import sys
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from portals.http import PoliteSession  # noqa: E402
from portals.models import OWNER_FIELDS, Account, delinquency_level, past_due  # noqa: E402
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
  due_date TEXT, kind TEXT, category TEXT, amount REAL, source TEXT, fetched_at TEXT,
  balance REAL, interest REAL
);
CREATE INDEX IF NOT EXISTS bills_acct ON bills(county_district, account_id);
CREATE INDEX IF NOT EXISTS bills_pin ON bills(pin, tax_year);
CREATE TABLE IF NOT EXISTS index_progress (
  county_district TEXT PRIMARY KEY, cursor TEXT, complete INTEGER DEFAULT 0, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS raw_responses (
  county_district TEXT, account_id TEXT, fetched_at TEXT, body BLOB,   -- zlib-compressed UTF-8
  PRIMARY KEY (county_district, account_id)
);
"""
DELINQUENCY_COLUMNS = {
    "portal_delinquent": "INTEGER", "pending_tax_sale": "INTEGER", "open_town_lien": "INTEGER",
    "lien_count": "INTEGER", "lien_open_balance": "REAL", "redeemed_liens": "INTEGER", "total_due": "REAL", "past_due_amount": "REAL", "past_due_interest": "REAL",
    "past_due_bills": "INTEGER", "oldest_past_due": "TEXT", "delinquency_level": "TEXT",
    "bankruptcy": "INTEGER", "liens_json": "TEXT",
}
ADDED_ACCOUNT_COLUMNS = ({f: "TEXT" for f in OWNER_FIELDS} | {"daniels_law": "INTEGER", "owners_collected": "INTEGER"}
                         | DELINQUENCY_COLUMNS | {"parsed_version": "INTEGER"})
ADDED_BILL_COLUMNS = {"balance": "REAL", "interest": "REAL"}
BILL_COLUMNS = ("county_district", "account_id", "pin", "tax_year", "quarter", "due_date", "kind", "category",
                "amount", "source", "fetched_at", "balance", "interest")
# Bump when parsers change what they extract; `rederive` re-parses stored raw responses below this.
PARSER_VERSION = 4


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deadline(max_minutes):
    return time.monotonic() + max_minutes * 60 if max_minutes is not None else None


def past(dl):
    return dl is not None and time.monotonic() > dl


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    for table, added in (("accounts", ADDED_ACCOUNT_COLUMNS), ("bills", ADDED_BILL_COLUMNS)):
        have = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        for col, typ in added.items():
            if col not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    db.commit()
    return db


def store_result(db, cd, account_id, res, ts, min_year, owners=None, owners_collected=None):
    """Write one parsed account + its bills. owners=None leaves stored owner fields untouched."""
    a = res.account
    bills = [b for b in res.bills if b.tax_year >= min_year]
    db.execute("DELETE FROM bills WHERE county_district=? AND account_id=?", (cd, account_id))
    db.executemany(
        f"INSERT INTO bills ({', '.join(BILL_COLUMNS)}) VALUES ({','.join('?' * len(BILL_COLUMNS))})",
        [(cd, b.account_id, b.pin, b.tax_year, b.quarter, b.due_date, b.kind, b.category, b.amount, b.source,
          ts, b.balance, b.interest) for b in bills],
    )
    # as of the moment the portal answered; bills from before min_year still count toward delinquency
    pd_ = past_due(res.bills, datetime.fromisoformat(ts).date())
    level = delinquency_level(pd_["past_due_bills"], a.lien_count, a.pending_tax_sale)
    sets = {
        "pin": a.pin, "property_class": a.property_class, "land_value": a.land_value,
        "improvement_value": a.improvement_value, "net_taxable": a.net_taxable, "status": a.status,
        "error": None, "fetched_at": ts, "daniels_law": a.daniels_law, "parsed_version": PARSER_VERSION,
        "portal_delinquent": a.portal_delinquent, "pending_tax_sale": a.pending_tax_sale,
        "open_town_lien": a.open_town_lien, "lien_count": a.lien_count, "lien_open_balance": a.lien_open_balance,
        "redeemed_liens": a.redeemed_liens, "total_due": a.total_due, "bankruptcy": a.bankruptcy,
        "liens_json": json.dumps(a.liens) if a.liens else None,
        **pd_, "delinquency_level": level,
    }
    if owners is not None:
        sets.update(dict(zip(OWNER_FIELDS, owners)), owners_collected=owners_collected)
    db.execute(f"UPDATE accounts SET {', '.join(f'{k}=?' for k in sets)} WHERE county_district=? AND account_id=?",
               (*sets.values(), cd, account_id))


def owner_values(acct, include_owners):
    """Owner/mailing values to store: none unless asked, and none for Daniel's Law accounts."""
    keep = include_owners and not acct.daniels_law
    return [getattr(acct, f) if keep else None for f in OWNER_FIELDS]


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

    n, last_cursor, stopped = 0, cursor, False
    dl = deadline(args.max_minutes)
    for cur, acct in accounts:
        if past(dl) and cur != last_cursor:
            stopped = True
            print(f"{town['name']}: time budget reached, stopping at cursor {str(cur).strip()}")
            break
        owners = owner_values(acct, args.include_owners)
        db.execute(
            f"""INSERT INTO accounts (county_district, account_id, pin, property_location, property_class,
                 daniels_law, {', '.join(OWNER_FIELDS)})
               VALUES (?,?,?,?,?,?,{','.join('?' * len(OWNER_FIELDS))})
               ON CONFLICT(county_district, account_id) DO UPDATE SET
                 pin=excluded.pin, property_location=excluded.property_location,
                 daniels_law=COALESCE(excluded.daniels_law, accounts.daniels_law),
                 {', '.join(f'{f}=COALESCE(excluded.{f}, accounts.{f})' for f in OWNER_FIELDS)}""",
            (cd, acct.account_id, acct.pin, acct.property_location, acct.property_class,
             acct.daniels_law, *owners),
        )
        n += 1
        if cur != last_cursor:
            db.execute("INSERT OR REPLACE INTO index_progress VALUES (?,?,0,?)", (cd, str(cur), now()))
            db.commit()
            last_cursor = cur
            print(f"{town['name']}: {n} accounts indexed (cursor {str(cur).strip() or 'start'})", flush=True)
    complete = 0 if (args.max_pages or stopped) else 1
    db.execute("INSERT OR REPLACE INTO index_progress VALUES (?,?,?,?)", (cd, str(last_cursor), complete, now()))
    db.commit()
    print(f"{town['name']}: done, {n} accounts this run, complete={bool(complete)}")


def cmd_fetch(db, args):
    town = TOWNS[args.town]
    cd = town["county_district"]
    portal = portal_for(args.town, PoliteSession(min_interval=args.interval))
    statuses = ("pending", "error") if args.retry_errors else ("pending",)
    cond = f"status IN ({','.join('?' * len(statuses))})"
    params = [cd, *statuses]
    if args.refresh_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.refresh_days)).isoformat(timespec="seconds")
        cond = f"({cond} OR (status IN ('done','no_bills') AND fetched_at < ?))"
        params.append(cutoff)
    if args.include_owners:
        # backfill accounts fetched earlier without owner collection
        cond = f"({cond} OR (status IN ('done','no_bills') AND COALESCE(owners_collected, 0) = 0))"
    if args.recheck_delinquent_days is not None:
        # re-check delinquent accounts more often than the general refresh
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.recheck_delinquent_days)).isoformat(timespec="seconds")
        cond = f"({cond} OR (COALESCE(delinquency_level, 'current') != 'current' AND fetched_at < ?))"
        params.append(cutoff)
    q = f"""SELECT account_id, pin, property_location, property_class FROM accounts
            WHERE county_district=? AND {cond} ORDER BY fetched_at IS NOT NULL, fetched_at, rowid"""
    if args.limit:
        q += " LIMIT ?"
        params.append(args.limit)
    todo = db.execute(q, params).fetchall()
    print(f"{town['name']}: {len(todo)} accounts to fetch")
    dl = deadline(args.max_minutes)
    for i, (account_id, pin, loc, cls) in enumerate(todo, 1):
        if past(dl):
            print(f"{town['name']}: time budget reached after {i - 1} accounts; re-run to continue")
            break
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
        store_result(db, cd, account_id, res, ts, args.min_year,
                     owners=owner_values(a, args.include_owners), owners_collected=int(args.include_owners))
        if a.daniels_law:
            db.execute("DELETE FROM raw_responses WHERE county_district=? AND account_id=?", (cd, account_id))
        elif args.keep_raw and args.include_owners and res.raw is not None:
            db.execute("INSERT OR REPLACE INTO raw_responses VALUES (?,?,?,?)",
                       (cd, account_id, ts, zlib.compress(res.raw.encode("utf-8"), 9)))
        db.commit()
        if i % 25 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)} fetched ({portal.http.requests_made} requests)", flush=True)


def cmd_rederive(db, args):
    """Re-parse stored raw responses with the current parsers. No network."""
    town = TOWNS[args.town]
    cd = town["county_district"]
    portal = portal_for(args.town, None)
    cond = "" if args.all else "AND COALESCE(a.parsed_version, 0) < ?"
    params = [cd] + ([] if args.all else [PARSER_VERSION])
    rows = db.execute(
        f"""SELECT a.account_id, a.pin, a.property_location, a.property_class, r.fetched_at, r.body
            FROM accounts a JOIN raw_responses r USING (county_district, account_id)
            WHERE a.county_district=? {cond}""", params).fetchall()
    print(f"{town['name']}: {len(rows)} stored responses to re-parse")
    dl = deadline(args.max_minutes)
    for i, (account_id, pin, loc, cls, fetched_at, body) in enumerate(rows, 1):
        if past(dl):
            print(f"{town['name']}: time budget reached after {i - 1}; re-run to continue")
            break
        try:
            res = portal.parse_raw(zlib.decompress(body).decode("utf-8"), Account(cd, account_id, pin, loc, cls or ""))
        except Exception as e:  # a response the current parser can't read: leave the row as it was
            print(f"  {pin}: could not re-parse ({e})")
            continue
        # raw responses are only stored when owner collection was on (never for Daniel's Law
        # accounts), so owner fields can be refreshed from them too
        a = res.account
        store_result(db, cd, account_id, res, fetched_at, args.min_year,
                     owners=owner_values(a, True), owners_collected=1)
        if i % 2000 == 0:
            db.commit()
            print(f"  {i}/{len(rows)} re-parsed", flush=True)
    db.commit()
    print(f"{town['name']}: re-parse done")


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
    print("\ndelinquency (as of each account's last fetch; 'unknown' = fetched before balances were parsed)")
    for slug, t in TOWNS.items():
        rows = db.execute("""SELECT COALESCE(delinquency_level, 'unknown'), COUNT(*), ROUND(SUM(past_due_amount), 0)
                             FROM accounts WHERE county_district=? AND status IN ('done','no_bills')
                             GROUP BY 1 ORDER BY 1""", (t["county_district"],)).fetchall()
        if rows:
            print(f"  {slug:<12} " + ", ".join(f"{lvl}: {n:,}" + (f" (${amt:,.0f})" if amt else "") for lvl, n, amt in rows))


def cmd_export(db, args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for table, order in (("accounts", "county_district, pin"), ("bills", "county_district, pin, due_date")):
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
        if args.redact_owners:
            cols = [c for c in cols if c not in OWNER_FIELDS]
        cur = db.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {order}")
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
    # Delinquent accounts, largest past-due amount first
    cols = [r[1] for r in db.execute("PRAGMA table_info(accounts)")]
    keep = ["county_district", "pin", "property_location", "property_class", "net_taxable",
            *([] if args.redact_owners else list(OWNER_FIELDS)), "daniels_law", *DELINQUENCY_COLUMNS, "fetched_at"]
    keep = [c for c in keep if c in cols]
    cur = db.execute(f"""SELECT {', '.join(keep)} FROM accounts
                         WHERE COALESCE(delinquency_level, 'current') NOT IN ('current')
                         ORDER BY COALESCE(past_due_amount, 0) + COALESCE(lien_open_balance, 0) DESC""")
    with open(out / "delinquent.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(keep)
        w.writerows(cur)
    cur = db.execute("""SELECT county_district, COALESCE(delinquency_level, 'unknown') AS level, COUNT(*) AS accounts,
                               ROUND(SUM(past_due_amount), 2) AS past_due_amount,
                               ROUND(SUM(past_due_interest), 2) AS past_due_interest,
                               ROUND(SUM(lien_open_balance), 2) AS lien_open_balance,
                               MIN(fetched_at) AS oldest_check, MAX(fetched_at) AS newest_check
                        FROM accounts WHERE status IN ('done','no_bills')
                        GROUP BY 1, 2 ORDER BY 1, 2""")
    with open(out / "delinquency_summary.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([c[0] for c in cur.description])
        w.writerows(cur)
    print(f"exported accounts.csv, bills.csv, annual.csv, delinquent.csv, delinquency_summary.csv to {out}")


def cmd_raw(db, args):
    row = db.execute(
        """SELECT r.body FROM raw_responses r JOIN accounts a USING (county_district, account_id)
           WHERE a.pin=?""", (args.pin,)).fetchone()
    if not row:
        sys.exit(f"no raw response stored for {args.pin}")
    print(zlib.decompress(row[0]).decode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("index", "fetch"):
        p = sub.add_parser(name)
        p.add_argument("--town", required=True, choices=TOWNS)
        p.add_argument("--interval", type=float, default=1.0, help="seconds between requests")
        p.add_argument("--max-minutes", type=float, help="stop cleanly after this many minutes")
        p.add_argument("--include-owners", action="store_true",
                       help="store owner names and mailing addresses (not for Daniel's Law accounts)")
        if name == "index":
            p.add_argument("--max-pages", type=int, help="stop after N pages (for pilots)")
            p.add_argument("--restart", action="store_true")
            p.add_argument("--start", help="start at this page (HLS) or block/lot key (WIPP)")
        else:
            p.add_argument("--limit", type=int)
            p.add_argument("--retry-errors", action="store_true")
            p.add_argument("--refresh-days", type=float, help="also re-fetch accounts fetched more than N days ago")
            p.add_argument("--min-year", type=int, default=2019, help="drop bills for tax years before this")
            p.add_argument("--keep-raw", action="store_true",
                           help="also store each raw portal response, compressed (requires --include-owners)")
            p.add_argument("--recheck-delinquent-days", type=float,
                           help="also re-fetch delinquent accounts last checked more than N days ago")
    p = sub.add_parser("rederive", help="re-parse stored raw responses with the current parsers (no network)")
    p.add_argument("--town", required=True, choices=TOWNS)
    p.add_argument("--all", action="store_true", help="re-parse every stored response, not only outdated ones")
    p.add_argument("--min-year", type=int, default=2019)
    p.add_argument("--max-minutes", type=float)
    sub.add_parser("status")
    p = sub.add_parser("export")
    p.add_argument("--out", default="data/portal/export")
    p.add_argument("--redact-owners", action="store_true", help="leave owner/mailing columns out of the export")
    p = sub.add_parser("raw", help="print the stored raw portal response for a parcel")
    p.add_argument("--pin", required=True)
    args = ap.parse_args(argv)
    if getattr(args, "keep_raw", False) and not args.include_owners:
        ap.error("--keep-raw contains owner data; use it together with --include-owners")
    db = connect(args.db)
    {"index": cmd_index, "fetch": cmd_fetch, "rederive": cmd_rederive, "status": cmd_status,
     "export": cmd_export, "raw": cmd_raw}[args.cmd](db, args)


if __name__ == "__main__":
    main()
