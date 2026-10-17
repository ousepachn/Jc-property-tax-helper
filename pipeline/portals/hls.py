"""HLS Systems 'Revenue Collection Application' (Jersey City, Hoboken).

JSON endpoints used by the public Property Tax Inquiry page:
  GET {base}/PropertyTaxInquiry/GetAccounts?page=N&searchType=Account&searchField=   (10 accounts/page)
  GET {base}/PropertyTaxInquiry/GetAccountDetails?accountNumber=N&interestThruDate=...
"""
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


def account_from_list_row(row, county_district):
    pin = make_pin(
        county_district,
        pin_part(row["SortBlock"], row.get("SortBlockSuffix")),
        pin_part(row["SortLot"], row.get("SortLotSuffix")),
        row.get("Qualifier"),
    )
    return Account(
        county_district=county_district,
        account_id=str(row["AccountNumber"]),
        pin=pin,
        property_location=(row.get("PropertyLocation") or "").strip(),
        property_class=(row.get("Class") or "").strip(),
    )


def parse_details(vm, account, source):
    """Turn an accountInquiryVM into bills. Payments and owner fields are ignored."""
    account.land_value = vm.get("Land")
    account.improvement_value = vm.get("Improvement")
    account.net_taxable = vm.get("NetTaxable")
    account.property_class = (vm.get("Class") or account.property_class or "").strip()
    bills = []
    for t in vm.get("Details") or []:
        billed, adjusted = t.get("Billed") or 0.0, t.get("Adjusted") or 0.0
        if not billed and not adjusted:
            continue
        kind = _kind(t.get("Description") or "")
        amount = billed
        if adjusted and not billed:
            kind, amount = f"{kind}_adjustment", adjusted
        bills.append(Bill(
            pin=account.pin, account_id=account.account_id, tax_year=int(t["TaxYear"]),
            quarter=int(t["Quarter"]) if t.get("Quarter") else None,
            due_date=_iso(t.get("DueDepositDate") or t.get("TransactionDate") or ""),
            kind=kind, amount=round(amount, 2), source=source,
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
        vm = r.json()["accountInquiryVM"]
        bills = parse_details(vm, account, self.source)
        account.status = "done" if bills else "no_bills"
        return FetchResult(account, bills)
