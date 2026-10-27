"""Tyler EnerGov Citizen Self Service: Jersey City's permit portal (jcnj.org/permitportal, since June 2023).

The public search page calls one JSON endpoint, no sign-in needed:
  GET  {base}/api/energov/search/criteria     an empty search (every field the search takes)
  POST {base}/api/energov/search/search       that search filled in; FilterModule 2 = permits

Each result carries the permit number, type and work class, status, apply / issue / finalize dates,
the work description, the address and the main parcel as a PAMS pin (0906_11508_18), so permits join
the tax records directly. Results hold no applicant or contractor names; we keep none either.
"""
from .http import PoliteSession

BASE = "https://jerseycitynj-energovpub.tylerhost.net/apps/selfservice"
TENANT = {"tenantId": "1", "tenantName": "JerseyCityNJProd", "Tyler-TenantUrl": "JerseyCityNJProd",
          "Tyler-Tenant-Culture": "en-US"}
PERMITS = 2           # FilterModule for permits
PAGE_SIZE = 100


class EnerGov:
    def __init__(self, session=None, base=BASE):
        self.http = session or PoliteSession(min_interval=1.0, timeout=120)
        self.base = base
        self._criteria = None

    def criteria(self):
        if self._criteria is None:
            r = self.http.get(f"{self.base}/api/energov/search/criteria", headers=TENANT)
            self._criteria = r.json()["Result"]
        return self._criteria

    def permits_page(self, page, page_size=PAGE_SIZE, newest_first=True, keyword=""):
        """One page of permits (all of them, or those matching `keyword` exactly), by issue date.
        Returns (rows, total_pages). Only the first 10,000 results of a search can be paged to."""
        body = dict(self.criteria())
        order = {"PageNumber": page, "PageSize": page_size, "SortBy": "IssueDate", "SortAscending": not newest_first}
        body.update(Keyword=keyword, ExactMatch=bool(keyword), SearchModule=1, FilterModule=PERMITS, **order)
        body["PermitCriteria"] = {**body["PermitCriteria"], **order}
        r = self.http.post(f"{self.base}/api/energov/search/search", json=body, headers=TENANT)
        res = r.json().get("Result")
        if not res:
            raise RuntimeError(f"EnerGov search failed on page {page}")
        return [parse(x) for x in res.get("EntityResults") or []], int(res.get("TotalPages") or 0)

    def permits_for(self, address, max_pages=20):
        """Every permit at a street address ('66 GAUTIER AVE'), all units included."""
        out, page, pages = [], 1, 1
        while page <= min(pages, max_pages):
            rows, pages = self.permits_page(page, keyword=address)
            out += rows
            page += 1
        return out


def _date(v):
    return v[:10] if v and not v.startswith(("0001", "2999")) else None


def parse(x):
    """A search result -> the public fields we keep."""
    pin = (x.get("MainParcel") or "").strip() or None
    return {
        "permit_no": x["CaseNumber"], "case_id": x.get("CaseId"), "pin": pin,
        "address": (x.get("AddressDisplay") or "").strip() or None,
        "case_type": (x.get("CaseType") or "").strip(), "work_class": (x.get("CaseWorkclass") or "").strip(),
        "status": (x.get("CaseStatus") or "").strip(),
        "apply_date": _date(x.get("ApplyDate")), "issue_date": _date(x.get("IssueDate")),
        "final_date": _date(x.get("FinalDate")), "expire_date": _date(x.get("ExpireDate")),
        "description": " ".join((x.get("Description") or "").split())[:300] or None,
    }
