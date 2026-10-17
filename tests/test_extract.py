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

    def fetch(self, account):
        self.fetched.append(account.account_id)
        if account.account_id in self.fail:
            raise RuntimeError("boom")
        bills = [Bill(account.pin, account.account_id, y, q, f"{y}-0{q}-01", "tax", 100.0)
                 for y in (2018, 2025, 2026) for q in (1, 2)]
        account.net_taxable = 1000.0
        account.status = "done"
        return FetchResult(account, bills)


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
