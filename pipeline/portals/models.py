"""Normalized records produced by every billing-portal client."""
from dataclasses import asdict, dataclass, field


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

    def __post_init__(self):
        if not self.category:
            self.category = categorize(self.kind)


OWNER_FIELDS = ("owner_name", "mailing_address", "mailing_address2", "mailing_city_state", "mailing_zip")


@dataclass
class FetchResult:
    account: Account
    bills: list[Bill] = field(default_factory=list)
    raw: str | None = None        # the portal's response body, as received

    def rows(self):
        return [asdict(b) for b in self.bills]
