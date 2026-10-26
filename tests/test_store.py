"""Store tests: the crawler against Postgres, SQLite -> Postgres import, and the Storage client.

The Postgres tests need a throwaway database and are skipped without one:
  TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres python -m pytest tests/test_store.py
They drop and recreate schema `portal` in that database.
"""
import os
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import extract_bills  # noqa: E402
import store  # noqa: E402
from test_extract import FakePortal  # noqa: E402

PG = os.environ.get("TEST_DATABASE_URL")
needs_pg = pytest.mark.skipif(not PG, reason="set TEST_DATABASE_URL to run Postgres tests")


class MemoryRaw:
    """Stands in for the Supabase bucket."""

    def __init__(self):
        self.objects = {}
        self.puts = 0

    def path(self, cd, account_id):
        return f"{cd}/{account_id}"

    def names(self, cd):
        return {self.path(c, a) for c, a in self.objects if c == cd}

    def put(self, cd, account_id, ts, text):
        self.puts += 1
        self.objects[(cd, account_id)] = text

    def get(self, cd, account_id):
        return self.objects.get((cd, account_id))

    def delete(self, cd, account_id):
        self.objects.pop((cd, account_id), None)


@pytest.fixture
def pg(monkeypatch):
    import psycopg
    with psycopg.connect(PG, autocommit=True) as c:
        c.execute(f"DROP SCHEMA IF EXISTS {store.PG_SCHEMA} CASCADE")
    raw = MemoryRaw()
    monkeypatch.setattr(extract_bills, "raw_store", lambda db: raw if db.dialect == "postgres" else store.SqliteRawStore(db))
    conn = psycopg.connect(PG, autocommit=True)
    conn.execute(f"SET search_path TO {store.PG_SCHEMA}")
    yield conn, raw
    conn.close()


def run(monkeypatch, portal, *argv):
    monkeypatch.setattr(extract_bills, "portal_for", lambda town, session: portal)
    extract_bills.main(["--db", PG, *argv])


@needs_pg
def test_crawl_cycle_on_postgres(pg, monkeypatch, tmp_path, capsys):
    conn, raw = pg
    p = FakePortal(n=3, fail={"3"})
    run(monkeypatch, p, "index", "--town", "union-city")
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 3
    assert conn.execute("SELECT complete FROM index_progress").fetchone()[0] == 1

    run(monkeypatch, p, "fetch", "--town", "union-city", "--include-owners", "--keep-raw")
    status = dict(conn.execute("SELECT account_id, status FROM accounts").fetchall())
    assert status == {"1": "done", "2": "done", "3": "error"}
    assert conn.execute("SELECT MIN(tax_year), COUNT(*) FROM bills WHERE account_id='1'").fetchone() == (2025, 4)
    owners = dict(conn.execute("SELECT account_id, owner_name FROM accounts").fetchall())
    assert owners["1"] == "OWNER 1" and owners["2"] is None            # Daniel's Law
    assert conn.execute("SELECT daniels_law FROM accounts WHERE account_id='2'").fetchone()[0] == 1
    assert set(raw.objects) == {("0910", "1")}                         # never for Daniel's Law

    p.fail.clear()
    run(monkeypatch, p, "fetch", "--town", "union-city", "--retry-errors", "--include-owners", "--keep-raw")
    assert conn.execute("SELECT delinquency_level, past_due_amount FROM accounts WHERE account_id='3'").fetchone() \
        == ("1_quarter", 100.0)

    # rederive reads the bucket, not the portal
    conn.execute("UPDATE accounts SET delinquency_level=NULL, parsed_version=0")
    p.fetched.clear()
    run(monkeypatch, p, "rederive", "--town", "union-city")
    assert p.fetched == []
    assert conn.execute("SELECT delinquency_level FROM accounts WHERE account_id='3'").fetchone()[0] == "1_quarter"

    capsys.readouterr()
    run(monkeypatch, p, "raw", "--pin", "0910_1_1")
    assert capsys.readouterr().out.strip() == "RAW 1"

    run(monkeypatch, p, "status")
    run(monkeypatch, p, "export", "--out", str(tmp_path / "x"), "--redact-owners")
    assert "owner_name" not in (tmp_path / "x" / "accounts.csv").read_text().splitlines()[0]
    annual = (tmp_path / "x" / "annual.csv").read_text().splitlines()
    assert annual[1].startswith("0910,0910_1_1,2025,200.0") or annual[1].startswith("0910,0910_1_1,2025,200")


@needs_pg
def test_tables_are_locked_down(pg, monkeypatch):
    conn, _ = pg
    run(monkeypatch, FakePortal(n=1), "index", "--town", "union-city")
    rls = dict(conn.execute("""SELECT relname, relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                               WHERE n.nspname = %s AND c.relkind = 'r'""", (store.PG_SCHEMA,)).fetchall())
    assert rls == {"accounts": True, "bills": True, "index_progress": True, "raw_responses": True}


@needs_pg
def test_import_sqlite_into_postgres(pg, monkeypatch, tmp_path):
    conn, raw = pg
    p = FakePortal(n=3)
    monkeypatch.setattr(extract_bills, "portal_for", lambda town, session: p)
    src = tmp_path / "old.sqlite"
    extract_bills.main(["--db", str(src), "index", "--town", "union-city"])
    extract_bills.main(["--db", str(src), "fetch", "--town", "union-city", "--include-owners", "--keep-raw"])

    run(monkeypatch, p, "import-sqlite", "--from", str(src))
    run(monkeypatch, p, "import-sqlite", "--from", str(src))           # idempotent
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM bills").fetchone()[0] == 12
    assert conn.execute("SELECT owner_name FROM accounts WHERE account_id='1'").fetchone()[0] == "OWNER 1"
    assert raw.objects == {("0910", "1"): "RAW 1", ("0910", "3"): "RAW 3"}
    assert conn.execute("SELECT COUNT(*) FROM accounts WHERE raw_fetched_at IS NOT NULL").fetchone()[0] == 2


def test_sqlite_file_from_before_raw_column_is_upgraded(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.sqlite"
    p = FakePortal(n=2)
    monkeypatch.setattr(extract_bills, "portal_for", lambda town, session: p)
    extract_bills.main(["--db", str(path), "index", "--town", "union-city"])
    extract_bills.main(["--db", str(path), "fetch", "--town", "union-city", "--include-owners", "--keep-raw"])
    db = sqlite3.connect(path)          # simulate an older file: drop the new column
    db.execute("ALTER TABLE accounts DROP COLUMN raw_fetched_at")
    db.commit()
    db.close()
    extract_bills.main(["--db", str(path), "status"])
    db = sqlite3.connect(path)
    assert db.execute("SELECT COUNT(*) FROM accounts WHERE raw_fetched_at IS NOT NULL").fetchone()[0] == 1


class FakeResponse:
    def __init__(self, status, body=b"", js=None):
        self.status_code, self.content, self._js = status, body, js

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self):
        self.headers, self.objects, self.calls = {}, {}, []
        self.fail_next = 0

    def get(self, url, timeout=None):
        self.calls.append(("GET", url))
        if "/bucket/" in url:
            return FakeResponse(404)
        key = url.split("/object/", 1)[1]
        return FakeResponse(200, self.objects[key]) if key in self.objects else FakeResponse(400)

    def post(self, url, data=None, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json, headers))
        if url.endswith("/bucket"):
            return FakeResponse(200)
        if "/object/list/" in url:
            prefix = f"{store.RAW_BUCKET}/{json['prefix']}"
            names = sorted(k[len(prefix):] for k in self.objects if k.startswith(prefix))
            return FakeResponse(200, js=[{"name": n} for n in names[json["offset"]:json["offset"] + json["limit"]]])
        if self.fail_next:
            self.fail_next -= 1
            return FakeResponse(503)
        self.objects[url.split("/object/", 1)[1]] = data
        return FakeResponse(200)

    def delete(self, url, json=None, timeout=None):
        for prefix in json["prefixes"]:
            self.objects.pop(f"{store.RAW_BUCKET}/{prefix}", None)
        return FakeResponse(200)


def test_supabase_raw_store_round_trip():
    s = FakeSession()
    rs = store.SupabaseRawStore("https://x.supabase.co/", "sb_secret_abc", session=s)
    assert s.headers == {"apikey": "sb_secret_abc"}                   # new keys never go in Authorization
    rs.ensure_bucket()
    assert s.calls[-1][2] == {"id": store.RAW_BUCKET, "name": store.RAW_BUCKET, "public": False}
    key = "   88  02    7       C0310   "                               # WIPP keys are space-padded
    rs.put("0910", key, "2026-01-01", '{"a": 1}')
    path = f"{store.RAW_BUCKET}/0910/88__02____7_______C0310.json.z"
    assert zlib.decompress(s.objects[path]) == b'{"a": 1}'
    assert rs.get("0910", key) == '{"a": 1}'
    rs.delete("0910", key)
    assert rs.get("0910", key) is None
    assert "Authorization" in store.SupabaseRawStore("https://x", "eyJhbGc", session=FakeSession()).http.headers


def test_public_bucket_is_refused():
    s = FakeSession()
    s.get = lambda url, timeout=None: FakeResponse(200, js={"public": True})
    with pytest.raises(RuntimeError, match="public"):
        store.SupabaseRawStore("https://x", "k", session=s).ensure_bucket()


OLD_BILLS = """CREATE TABLE bills (county_district TEXT, account_id TEXT, pin TEXT, tax_year INTEGER, quarter INTEGER,
  due_date TEXT, kind TEXT, category TEXT, amount REAL, source TEXT, fetched_at TEXT, balance REAL, interest REAL);
CREATE INDEX bills_acct ON bills(county_district, account_id);
CREATE INDEX bills_pin ON bills(pin, tax_year);"""
EXPORT_HEADER = "county_district,account_id,pin,tax_year,quarter,due_date,kind,category,amount,source,fetched_at,balance,interest"


def test_old_bills_layout_is_slimmed_and_export_is_unchanged(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.sqlite"
    p = FakePortal(n=2)
    monkeypatch.setattr(extract_bills, "portal_for", lambda town, session: p)
    extract_bills.main(["--db", str(path), "index", "--town", "union-city"])
    db = sqlite3.connect(path)         # rebuild the file the way the previous version laid out bills
    db.executescript("DROP TABLE bills;" + OLD_BILLS)
    db.execute("UPDATE accounts SET fetched_at='2026-01-01T00:00:00+00:00', status='done'")
    db.execute("ALTER TABLE accounts DROP COLUMN source")
    db.executemany("INSERT INTO bills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [("0910", "1", "0910_1_1", 2025, q, f"2025-0{q}-01", "tax", "property_tax", 100.0, "wipp:0910",
                     "2026-01-01T00:00:00+00:00", 0.0, 0.0) for q in (1, 2)])
    db.commit()
    db.close()

    extract_bills.main(["--db", str(path), "export", "--out", str(tmp_path / "x")])
    db = sqlite3.connect(path)
    assert [r[1] for r in db.execute("PRAGMA table_info(bills)")] == list(extract_bills.BILL_COLUMNS)
    assert {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='bills'")} == {"bills_acct"}
    assert db.execute("SELECT source FROM accounts WHERE account_id='1'").fetchone()[0] == "wipp:0910"
    lines = (tmp_path / "x" / "bills.csv").read_text().splitlines()
    assert lines[0] == EXPORT_HEADER
    assert lines[1] == "0910,1,0910_1_1,2025,1,2025-01-01,tax,property_tax,100.0,wipp:0910,2026-01-01T00:00:00+00:00,0.0,0.0"
    assert (tmp_path / "x" / "annual.csv").read_text().splitlines()[1].startswith("0910,0910_1_1,2025,200")


def test_fetch_writes_slim_bills_and_account_source(tmp_path, monkeypatch):
    p = FakePortal(n=1)
    monkeypatch.setattr(extract_bills, "portal_for", lambda town, session: p)
    path = tmp_path / "t.sqlite"
    extract_bills.main(["--db", str(path), "index", "--town", "union-city"])
    extract_bills.main(["--db", str(path), "fetch", "--town", "union-city"])
    extract_bills.main(["--db", str(path), "export", "--out", str(tmp_path / "x")])
    lines = (tmp_path / "x" / "bills.csv").read_text().splitlines()
    assert lines[0] == EXPORT_HEADER and len(lines) == 5
    assert lines[1].split(",")[2] == "0910_1_1"


def test_supabase_store_lists_and_retries(monkeypatch):
    monkeypatch.setattr(store.SupabaseRawStore, "RETRY_DELAYS", (0, 0))
    s = FakeSession()
    rs = store.SupabaseRawStore("https://x", "sb_secret_k", session=s)
    s.fail_next = 2                                                # two 503s, then it goes through
    rs.put("0906", "1", "t", "a")
    rs.put("0906", "2", "t", "b")
    assert rs.names("0906") == {"0906/1.json.z", "0906/2.json.z"} and rs.names("0910") == set()
    s.fail_next = 5
    with pytest.raises(RuntimeError, match="HTTP 503"):
        rs.put("0906", "3", "t", "c")


@needs_pg
def test_import_resumes_raw_copy(pg, monkeypatch, tmp_path):
    conn, raw = pg
    p = FakePortal(n=3)
    monkeypatch.setattr(extract_bills, "portal_for", lambda town, session: p)
    src = tmp_path / "old.sqlite"
    extract_bills.main(["--db", str(src), "index", "--town", "union-city"])
    extract_bills.main(["--db", str(src), "fetch", "--town", "union-city", "--include-owners", "--keep-raw"])
    # an earlier run copied the tables and one response, then died
    run(monkeypatch, p, "import-sqlite", "--from", str(src), "--skip-raw")
    assert conn.execute("SELECT COUNT(*) FROM accounts WHERE raw_fetched_at IS NOT NULL").fetchone()[0] == 0
    raw.objects[("0910", "1")] = "RAW 1"
    conn.execute("UPDATE accounts SET raw_fetched_at='stale'")      # marks left by the old import
    run(monkeypatch, p, "import-sqlite", "--from", str(src), "--raw-only")
    assert raw.puts == 1 and set(raw.objects) == {("0910", "1"), ("0910", "3")}
    marked = dict(conn.execute("SELECT account_id, raw_fetched_at IS NOT NULL FROM accounts").fetchall())
    assert marked == {"1": True, "2": False, "3": True}             # 2 is Daniel's Law: never stored
