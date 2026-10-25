"""Where the crawler keeps its data: a local SQLite file, or a hosted Postgres (Supabase).

  connect("data/portal/bills.sqlite")                 # local file (development, tests)
  connect("postgresql://...")                         # hosted database; tables live in schema `portal`

The crawler writes one SQL dialect (SQLite's, with ? placeholders); `Db` translates it for Postgres.
Raw portal responses are large (they hold the full payment ledger), so on Postgres they go to a
private Supabase Storage bucket instead of the database: see `raw_store`.

Nothing here prints connection strings or keys.
"""
import os
import re
import sqlite3
import zlib
from pathlib import Path
from urllib.parse import quote

PG_SCHEMA = "portal"
RAW_BUCKET = "portal-raw"
SCHEMA_LOCK_ID = 906_0910


def is_postgres_url(target):
    return str(target).startswith(("postgres://", "postgresql://"))


class Db:
    """Thin DB-API wrapper: same calls and SQL for SQLite and Postgres."""

    def __init__(self, conn, dialect):
        self.conn, self.dialect = conn, dialect

    def _sql(self, sql):
        if self.dialect == "postgres":
            # SQLite-only words in the shared SQL, and placeholders
            sql = re.sub(r"\bBLOB\b", "BYTEA", sql)
            sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql)
            sql = sql.replace("?", "%s")
        return sql

    @staticmethod
    def _params(params):
        # Postgres INTEGER columns reject Python booleans; SQLite stores them as 0/1 anyway
        return tuple(int(p) if isinstance(p, bool) else p for p in params)

    def execute(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), self._params(params))
        return cur

    def executemany(self, sql, rows):
        cur = self.conn.cursor()
        cur.executemany(self._sql(sql), [self._params(r) for r in rows])
        return cur

    def executescript(self, script):
        if self.dialect == "sqlite":
            self.conn.executescript(script)
            return
        script = re.sub(r"--[^\n]*", "", script)   # comments may contain semicolons
        for stmt in (s.strip() for s in script.split(";")):
            if stmt:
                self.execute(stmt)

    def columns(self, table):
        if self.dialect == "sqlite":
            return [r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")]
        rows = self.execute("""SELECT column_name FROM information_schema.columns
                               WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position""",
                            (PG_SCHEMA, table)).fetchall()
        return [r[0] for r in rows]

    def schema_lock(self):
        """Postgres: serialize schema changes between jobs that start at the same time (held until commit)."""
        if self.dialect == "postgres":
            self.execute("SELECT pg_advisory_xact_lock(?)", (SCHEMA_LOCK_ID,))

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


def connect(target):
    """Open the store. `target` is a SQLite path or a postgresql:// URL."""
    if is_postgres_url(target):
        import psycopg   # only needed for the hosted database

        if re.search(r":6543(/|$)", str(target)):
            raise SystemExit("DATABASE_URL uses Supabase's transaction pooler (port 6543); "
                             "use the Session pooler connection string (port 5432)")

        conn = psycopg.connect(str(target), autocommit=False, keepalives=1, keepalives_idle=30,
                               prepare_threshold=None)   # poolers do not keep prepared statements
        db = Db(conn, "postgres")
        db.schema_lock()
        db.execute(f"CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA}")
        db.execute(f"SET search_path TO {PG_SCHEMA}")
        db.commit()
        return db
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    return Db(sqlite3.connect(path), "sqlite")


def lock_down(db, tables):
    """Postgres only: keep tables out of reach of Supabase's public API keys.

    The tables live in schema `portal`, which Supabase's REST API does not expose; row level
    security with no policies is a second lock (only the database owner can read them)."""
    if db.dialect != "postgres":
        return
    db.execute(f"REVOKE ALL ON SCHEMA {PG_SCHEMA} FROM PUBLIC")
    for role in ("anon", "authenticated"):
        if db.execute("SELECT 1 FROM pg_roles WHERE rolname = ?", (role,)).fetchone():
            db.execute(f"REVOKE ALL ON SCHEMA {PG_SCHEMA} FROM {role}")
            db.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {PG_SCHEMA} FROM {role}")
    locked = {r[0] for r in db.execute("""SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                                          WHERE n.nspname = ? AND c.relrowsecurity""", (PG_SCHEMA,))}
    for t in tables:
        if t not in locked:
            db.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")


# --- raw portal responses ------------------------------------------------------------------------

class SqliteRawStore:
    """Raw responses in the local SQLite file (table raw_responses, zlib-compressed)."""

    def __init__(self, db):
        self.db = db

    def put(self, cd, account_id, ts, text):
        self.db.execute("""INSERT INTO raw_responses VALUES (?,?,?,?)
                           ON CONFLICT (county_district, account_id) DO UPDATE SET
                             fetched_at = excluded.fetched_at, body = excluded.body""",
                        (cd, account_id, ts, zlib.compress(text.encode("utf-8"), 9)))

    def get(self, cd, account_id):
        row = self.db.execute("SELECT body FROM raw_responses WHERE county_district=? AND account_id=?",
                              (cd, account_id)).fetchone()
        return zlib.decompress(row[0]).decode("utf-8") if row else None

    def delete(self, cd, account_id):
        self.db.execute("DELETE FROM raw_responses WHERE county_district=? AND account_id=?", (cd, account_id))


class SupabaseRawStore:
    """Raw responses as objects in a private Supabase Storage bucket: <town>/<account>.json.z"""

    def __init__(self, url, key, bucket=RAW_BUCKET, session=None):
        import requests

        self.base = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.http = session or requests.Session()
        self.http.headers["apikey"] = key
        if key.startswith("eyJ"):   # legacy service_role JWT; new sb_secret_ keys go in apikey only
            self.http.headers["Authorization"] = f"Bearer {key}"

    def _path(self, cd, account_id):
        return f"{cd}/{quote(account_id.strip().replace(' ', '_'), safe='')}.json.z"

    def ensure_bucket(self):
        r = self.http.get(f"{self.base}/bucket/{self.bucket}", timeout=30)
        if r.status_code == 200:
            if r.json().get("public"):
                raise RuntimeError(f"storage bucket {self.bucket} is public; make it private first")
            return
        r = self.http.post(f"{self.base}/bucket", json={"id": self.bucket, "name": self.bucket, "public": False},
                           timeout=30)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"could not create storage bucket {self.bucket}: HTTP {r.status_code}")

    def put(self, cd, account_id, ts, text):
        r = self.http.post(f"{self.base}/object/{self.bucket}/{self._path(cd, account_id)}",
                           data=zlib.compress(text.encode("utf-8"), 9),
                           headers={"Content-Type": "application/octet-stream", "x-upsert": "true"}, timeout=60)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"raw upload failed: HTTP {r.status_code}")

    def get(self, cd, account_id):
        r = self.http.get(f"{self.base}/object/{self.bucket}/{self._path(cd, account_id)}", timeout=60)
        if r.status_code in (400, 404):
            return None
        r.raise_for_status()
        return zlib.decompress(r.content).decode("utf-8")

    def delete(self, cd, account_id):
        self.http.delete(f"{self.base}/object/{self.bucket}", json={"prefixes": [self._path(cd, account_id)]},
                         timeout=30)


def raw_store(db):
    """SQLite keeps raw responses in its own file; Postgres needs SUPABASE_URL + SUPABASE_SECRET_KEY.
    Returns None when raw responses cannot be stored."""
    if db.dialect == "sqlite":
        return SqliteRawStore(db)
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SECRET_KEY")
    return SupabaseRawStore(url, key) if url and key else None
