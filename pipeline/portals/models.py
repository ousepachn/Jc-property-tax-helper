"""Normalized records produced by every billing-portal client."""
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta


def pin_part(base, suffix=""):
    """'00301' + '' -> '301'; '1' + '01' -> '1.01'. Same rules as MOD-IV / NJOGIS PAMS_PIN."""
    base = (base or "").strip().lstrip("0") or "0"
    suffix = (suffix or "").strip()
    return f"{base}.{suffix}" if suffix else base


def make_pin(county_district, block, lot, qualifier=""):
    qualifier = (qualifier or "").strip()
    return "_".join(p for p in (county_district, block, lot, qualifier) if p)


@dataclass
class Account:
    county_district: str          # e.g. '0906'
    account_id: str               # portal's own account key
    pin: str                      # PAMS_PIN-style id, joins to MOD-IV / NJOGIS
    property_location: str = ""
    property_class: str = ""
    land_value: float | None = None
    improvement_value: float | None = None
    net_taxable: float | None = None
    status: str = "pending"       # pending | done | no_bills | error
    # Owner/mailing fields are parsed when the portal shows them, but the crawler only stores
    # them with --include-owners, and never for accounts flagged under Daniel's Law.
    owner_name: str | None = None
    mailing_address: str | None = None
    mailing_address2: str | None = None
    mailing_city_state: str | None = None
    mailing_zip: str | None = None
    daniels_law: bool | None = None
    # Delinquency as the portal reports it (HLS has explicit flags; WIPP only per-bill balances).
    # These are not owner data and are stored for every account.
    portal_delinquent: bool | None = None
    pending_tax_sale: bool | None = None
    open_town_lien: bool | None = None
    lien_count: int | None = None          # open (unredeemed) tax-sale liens
    lien_open_balance: float | None = None
    redeemed_liens: int | None = None      # past liens since paid off; history, not current delinquency
    total_due: float | None = None
    bankruptcy: bool | None = None
    liens: list | None = None               # open liens: certificate, sale_date, holder, amounts


PROPERTY_TAX_KINDS = {"tax", "added", "omitted"}
APPEAL_MARKERS = ("tax_court", "hudson_cty_bd", "county_bd", "assessor")


def categorize(kind):
    """property_tax: regular/added/omitted bills. appeal_adjustment: tax court, county board or
    assessor changes. other: payments bookkeeping, utilities, SID, hotel tax, fees."""
    if kind in PROPERTY_TAX_KINDS:
        return "property_tax"
    if any(m in kind for m in APPEAL_MARKERS):
        return "appeal_adjustment"
    return "other"


@dataclass
class Bill:
    pin: str
    account_id: str
    tax_year: int
    quarter: int | None           # 1-4, None when the portal doesn't say
    due_date: str                 # ISO yyyy-mm-dd
    kind: str                     # 'tax', 'added', 'adjustment', ... (portal wording, normalized)
    amount: float                 # billed (positive) or adjustment (signed)
    source: str = ""              # portal id, e.g. 'hls:JerseyCity'
    category: str = ""            # see categorize(); filled in __post_init__
    balance: float | None = None  # unpaid amount on this bill when fetched (None if the portal doesn't say)
    interest: float | None = None # interest owed on this bill when fetched

    def __post_init__(self):
        if not self.category:
            self.category = categorize(self.kind)


GRACE_DAYS = 10   # NJ: no interest if paid within 10 days of the due date (N.J.S.A. 54:4-67)


def past_due(bills, as_of, grace_days=GRACE_DAYS):
    """Summarize unpaid property-tax bills whose due date + grace period is before as_of (a date)."""
    cutoff = as_of - timedelta(days=grace_days)
    due = [b for b in bills
           if b.category == "property_tax" and (b.balance or 0) > 0.005 and b.due_date
           and date.fromisoformat(b.due_date) < cutoff]
    return {
        "past_due_amount": round(sum(b.balance for b in due), 2),
        "past_due_interest": round(sum(b.interest or 0 for b in due), 2),
        "past_due_bills": len(due),
        "oldest_past_due": min((b.due_date for b in due), default=None),
    }


def delinquency_level(past_due_bills, lien_count=0, pending_tax_sale=False):
    """current | 1_quarter | 2_3_quarters | 4plus_quarters | lien (lien sold or pending tax sale)."""
    if (lien_count or 0) > 0 or pending_tax_sale:
        return "lien"
    if not past_due_bills:
        return "current"
    if past_due_bills == 1:
        return "1_quarter"
    return "2_3_quarters" if past_due_bills <= 3 else "4plus_quarters"


OWNER_FIELDS = ("owner_name", "mailing_address", "mailing_address2", "mailing_city_state", "mailing_zip")


@dataclass
class FetchResult:
    account: Account
    bills: list[Bill] = field(default_factory=list)
    raw: str | None = None        # the portal's response body, as received

    def rows(self):
        return [asdict(b) for b in self.bills]
