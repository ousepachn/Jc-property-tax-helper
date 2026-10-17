"""Crawler loop tests with a fake portal (no network)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import extract_bills  # noqa: E402
from portals.models import Account, Bill, FetchResult  # noqa: E402


class FakePortal:
    def __init__(self, n=5, fail=()):
        self.n, self.fail = n, set(fail)
        self.fetched = []

        class H:
            requests_made = 0
        self.http = H()

    def iter_accounts(self, start_page=1, max_pages=None):
        for i in range(start_page, self.n + 1):
            yield i, Account("0910", str(i), f"0910_{i}_1", f"{i} MAIN ST", "2")

    @staticmethod
    def _owner(account):
        account.owner_name = f"OWNER {account.account_id}"
        account.mailing_address = f"{account.account_id} MAIL ST"
        account.mailing_zip = "07087"
        account.daniels_law = account.account_id == "2"   # account 2 is protected

    def fetch(self, account):
        self.fetched.append(account.account_id)
        if account.account_id in self.fail:
            raise RuntimeError("boom")
        bills = [Bill(account.pin, account.account_id, y, q, f"{y}-0{q}-01", "tax", 100.0)
                 for y in (2018, 2025, 2026) for q in (1, 2)]
        account.net_taxable = 1000.0
        account.status = "done"
        self._owner(account)
        return FetchResult(account, bills, raw=f"RAW {account.account_id}")


def run(tmp_path, monkeypatch, portal, *argv):
    monkeypatch.setattr(extract_bills, "portal_for", lambda town, session: portal)
    extract_bills.main(["--db", str(tmp_path / "t.sqlite"), *argv])
    return sqlite3.connect(tmp_path / "t.sqlite")


def test_index_then_fetch_then_resume(tmp_path, monkeypatch):
    p = FakePortal(n=5, fail={"3"})
    db = run(tmp_path, monkeypatch, p, "index", "--town", "union-city")
    assert db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 5
    assert db.execute("SELECT complete FROM index_progress").fetchone()[0] == 1

    db = run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city", "--limit", "2")
    assert p.fetched == ["1", "2"]

    db = run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city")
    assert p.fetched == ["1", "2", "3", "4", "5"]
    status = dict(db.execute("SELECT account_id, status FROM accounts").fetchall())
    assert status["3"] == "error" and status["5"] == "done"
    # min-year (default 2019) drops the 2018 bills
    assert db.execute("SELECT MIN(tax_year) FROM bills").fetchone()[0] == 2025
    assert db.execute("SELECT COUNT(*) FROM bills WHERE account_id='1'").fetchone()[0] == 4

    p.fail.clear()
    db = run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city", "--retry-errors")
    assert p.fetched[-1] == "3"
    assert db.execute("SELECT COUNT(*) FROM accounts WHERE status='done'").fetchone()[0] == 5


def test_refresh_and_time_budget(tmp_path, monkeypatch):
    p = FakePortal(n=3)
    run(tmp_path, monkeypatch, p, "index", "--town", "union-city")
    run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city")
    p.fetched.clear()
    run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city")           # nothing pending
    assert p.fetched == []
    # --refresh-days -1 puts the cutoff in the future, so every fetched account is due again
    run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city", "--refresh-days", "-1", "--max-minutes", "0")
    assert p.fetched == []                                                  # zero budget: stop before fetching
    db = run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city", "--refresh-days", "-1")
    assert sorted(p.fetched) == ["1", "2", "3"]
    db.close()


def test_owner_fields_only_with_flag_and_never_for_daniels_law(tmp_path, monkeypatch):
    p = FakePortal(n=3)
    run(tmp_path, monkeypatch, p, "index", "--town", "union-city")
    db = run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city", "--keep-raw", "--include-owners")
    rows = dict(db.execute("SELECT account_id, owner_name FROM accounts").fetchall())
    assert rows == {"1": "OWNER 1", "2": None, "3": "OWNER 3"}
    assert db.execute("SELECT daniels_law FROM accounts WHERE account_id='2'").fetchone()[0] == 1
    raw = {r[0] for r in db.execute("SELECT account_id FROM raw_responses")}
    assert raw == {"1", "3"}

    # Re-fetching without the flag clears what was stored before
    db = run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city", "--refresh-days", "-1")
    assert db.execute("SELECT COUNT(*) FROM accounts WHERE owner_name IS NOT NULL").fetchone()[0] == 0


def test_raw_command_round_trip(tmp_path, monkeypatch, capsys):
    p = FakePortal(n=1)
    run(tmp_path, monkeypatch, p, "index", "--town", "union-city")
    run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city", "--keep-raw", "--include-owners")
    capsys.readouterr()
    run(tmp_path, monkeypatch, p, "raw", "--pin", "0910_1_1")
    assert capsys.readouterr().out.strip() == "RAW 1"


def test_keep_raw_requires_include_owners(tmp_path, monkeypatch):
    import pytest
    with pytest.raises(SystemExit):
        run(tmp_path, monkeypatch, FakePortal(n=1), "fetch", "--town", "union-city", "--keep-raw")


def test_owner_backfill_and_export_redaction(tmp_path, monkeypatch):
    p = FakePortal(n=2)
    run(tmp_path, monkeypatch, p, "index", "--town", "union-city")
    run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city")                 # public-repo run: no owners
    p.fetched.clear()
    db = run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city", "--include-owners")
    assert sorted(p.fetched) == ["1", "2"]                                        # backfilled
    assert db.execute("SELECT owner_name FROM accounts WHERE account_id='1'").fetchone()[0] == "OWNER 1"
    p.fetched.clear()
    run(tmp_path, monkeypatch, p, "fetch", "--town", "union-city", "--include-owners")
    assert p.fetched == []                                                        # nothing left to backfill

    run(tmp_path, monkeypatch, p, "export", "--out", str(tmp_path / "x"), "--redact-owners")
    header = (tmp_path / "x" / "accounts.csv").read_text().splitlines()[0]
    assert "owner_name" not in header and "mailing_address" not in header
    run(tmp_path, monkeypatch, p, "export", "--out", str(tmp_path / "y"))
    assert "OWNER 1" in (tmp_path / "y" / "accounts.csv").read_text()
