"""HLS Systems 'Revenue Collection Application' (Jersey City, Hoboken).

JSON endpoints used by the public Property Tax Inquiry page:
  GET {base}/PropertyTaxInquiry/GetAccounts?page=N&searchType=Account&searchField=   (10 accounts/page)
  GET {base}/PropertyTaxInquiry/GetAccountDetails?accountNumber=N&interestThruDate=...
"""
import json
import re
import time
from datetime import datetime

from .http import PoliteSession
from .models import Account, Bill, FetchResult, make_pin, pin_part

ROOT = "https://apps.hlssystems.com"
PAGE_SIZE = 10


def _kind(description):
    d = description.strip().lower()
    if d.startswith("taxes"):
        return "tax"
    if d.startswith("added"):
        return "added"
    if d.startswith("omit"):
        return "omitted"
    return re.sub(r"\s+(bill|adjustment)$", "", d).replace(" ", "_") or "other"


def _iso(mmddyyyy):
    try:
        return datetime.strptime(mmddyyyy.strip(), "%m/%d/%Y").date().isoformat()
    except (ValueError, AttributeError):
        return ""


def _owner_fields(src, account):
    """Copy owner/mailing fields from a list row or accountInquiryVM onto the account."""
    def clean(k):
        return (src.get(k) or "").strip() or None
    account.owner_name = clean("OwnerName")
    account.mailing_address = clean("Address")
    account.mailing_address2 = clean("Address2")
    account.mailing_city_state = clean("CityState")
    account.mailing_zip = clean("PostalCode")
    account.daniels_law = bool(src.get("DanielsLaw"))


def account_from_list_row(row, county_district):
    pin = make_pin(
        county_district,
        pin_part(row["SortBlock"], row.get("SortBlockSuffix")),
        pin_part(row["SortLot"], row.get("SortLotSuffix")),
        row.get("Qualifier"),
    )
    account = Account(
        county_district=county_district,
        account_id=str(row["AccountNumber"]),
        pin=pin,
        property_location=(row.get("PropertyLocation") or "").strip(),
        property_class=(row.get("Class") or "").strip(),
    )
    _owner_fields(row, account)
    return account


def parse_details(vm, account, source):
    """Turn an accountInquiryVM into bills (payments are skipped; they stay in the raw response)."""
    _owner_fields(vm, account)
    account.land_value = vm.get("Land")
    account.improvement_value = vm.get("Improvement")
    account.net_taxable = vm.get("NetTaxable")
    account.property_class = (vm.get("Class") or account.property_class or "").strip()
    account.portal_delinquent = bool(vm.get("DelinquentStatus"))
    account.pending_tax_sale = bool(vm.get("PendingTaxsale"))
    account.open_town_lien = bool(vm.get("OpenTownLien"))
    # LienCount also counts redeemed liens, so classify each certificate instead
    liens = vm.get("AccountLiens") or []
    open_liens = [lien for lien in liens if (lien.get("OpenBalance") or 0) > 0
                  or (lien.get("Status") or "").strip().lower() not in ("redeemed", "cancelled", "canceled")]
    account.lien_count = len(open_liens)
    account.lien_open_balance = round(sum(lien.get("OpenBalance") or 0 for lien in open_liens), 2)
    account.redeemed_liens = len(liens) - len(open_liens)
    account.total_due = vm.get("TotalDue")
    bills = []
    for t in vm.get("Details") or []:
        billed, adjusted = t.get("Billed") or 0.0, t.get("Adjusted") or 0.0
        if not billed and not adjusted:
            continue
        kind = _kind(t.get("Description") or "")
        amount, balance, interest = billed, t.get("Balance"), t.get("Interest")
        if adjusted and not billed:
            kind, amount, balance, interest = f"{kind}_adjustment", adjusted, None, None
        bills.append(Bill(
            pin=account.pin, account_id=account.account_id, tax_year=int(t["TaxYear"]),
            quarter=int(t["Quarter"]) if t.get("Quarter") else None,
            due_date=_iso(t.get("DueDepositDate") or t.get("TransactionDate") or ""),
            kind=kind, amount=round(amount, 2), source=source,
            balance=None if balance is None else round(balance, 2),
            interest=None if interest is None else round(interest, 2),
        ))
    return bills


class HlsPortal:
    def __init__(self, town, county_district, session=None):
        self.town = town                      # 'JerseyCity' | 'Hoboken'
        self.county_district = county_district
        self.base = f"{ROOT}/{town}/PropertyTaxInquiry"
        self.source = f"hls:{town}"
        self.http = session or PoliteSession()

    def count_accounts(self):
        r = self.http.get(f"{self.base}/GetAccounts", params={"page": 1, "searchType": "Account", "searchField": ""})
        return r.json()["recCount"]

    def iter_accounts(self, start_page=1, max_pages=None):
        """Yield (page, Account) for every account in the town."""
        total = self.count_accounts()
        last_page = (total + PAGE_SIZE - 1) // PAGE_SIZE
        if max_pages:
            last_page = min(last_page, start_page + max_pages - 1)
        for page in range(start_page, last_page + 1):
            r = self.http.get(f"{self.base}/GetAccounts",
                              params={"page": page, "searchType": "Account", "searchField": ""})
            for row in r.json().get("accounts", []):
                yield page, account_from_list_row(row, self.county_district)

    def fetch(self, account):
        r = self.http.get(f"{self.base}/GetAccountDetails", params={
            "accountNumber": account.account_id,
            "interestThruDate": time.strftime("%a %b %d %Y"),
        })
        return self.parse_raw(r.text, account)

    def parse_raw(self, raw, account):
        """Parse a stored GetAccountDetails response (no network)."""
        vm = json.loads(raw)["accountInquiryVM"]
        bills = parse_details(vm, account, self.source)
        account.status = "done" if bills else "no_bills"
        return FetchResult(account, bills, raw=raw)
