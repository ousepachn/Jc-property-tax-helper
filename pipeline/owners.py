"""Classify property owners from owner name + mailing address (public tax-roll fields).

Categories:
  owner_occupied      a person (not an entity) whose mailing address is the property itself
  individual_investor a person whose mailing address is elsewhere (absentee landlord)
  small_llc           "mom and pop": an LLC/company holding fewer than CORPORATE_MIN_PARCELS parcels
  corporate           an entity holding CORPORATE_MIN_PARCELS+ parcels, or an institutional name
  trust_estate        trusts and estates (usually family vehicles)
  public_nonprofit    government, housing authority, religious, nonprofit, condo/homeowner associations
  unknown             no owner name (e.g. Daniel's Law protected, or not collected)

Portfolio size counts parcels sharing the same owner name (care-of part removed) or, for entities,
the same mailing address or the same care-of party ("450 SEVENTH LLC % HOTHEM"): one operator often
holds many single-asset LLCs managed from one office.
"""
import re
from collections import Counter

CORPORATE_MIN_PARCELS = 5

ENTITY = re.compile(
    r"\b(L\.?\s?L\.?\s?C|INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|L\.?P|L\.?L\.?P|LTD|HOLDINGS?|"
    r"PROPERTIES|PROPERTY|REALTY|ASSOCIATES|ASSOC|PARTNERS|PARTNERSHIP|GROUP|VENTURES?|CAPITAL|FUND|"
    r"BANK|MANAGEMENT|MGMT|ENTERPRISES?|DEVELOPMENT|DEVELOPERS?|INVESTMENTS?|INVESTORS?|EQUITIES|"
    r"REIT|TRUSTCO|URBAN RENEWAL|ACQUISITIONS?|OWNER|OPERATING|INVEST\w*|DEVEL\w*|ELECTRIC|UTILITY|"
    r"RAILROAD|RAILWAY|TELEPHONE|VERIZON)\b")
INSTITUTIONAL = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|L\.?P|REIT|FUND|BANK|CAPITAL|NATIONAL|FEDERAL|MORTGAGE|"
    r"URBAN RENEWAL|ACQUISITIONS?|OPERATING|HOLDINGS|ELECTRIC|GAS CO|UTILITY|PSE ?G|RAILROAD|RAILWAY|"
    r"TELEPHONE|VERIZON)\b")
TRUST = re.compile(r"\b(TRUST|TRUSTEES?|TRSTE|TR|ESTATE OF|EST OF|EXECUTO?R|EXECUTRIX|LIVING TR)\b")
PUBLIC = re.compile(
    r"\b(CITY OF|TOWN OF|TOWNSHIP|COUNTY OF|STATE OF|HOUSING AUTH|AUTHORITY|BOARD OF EDUCATION|"
    r"BD OF ED|UNITED STATES|USA|PORT AUTH|CHURCH|PARISH|DIOCESE|CONGREGATION|TEMPLE|SYNAGOGUE|MOSQUE|"
    r"SOCIETY|UNIVERSITY|COLLEGE|SCHOOL|HOSPITAL|FOUNDATION|CONDOMINIUM ASSOC\w*|CONDO ASSOC\w*|"
    r"HOMEOWNERS ASSOC\w*|HOME OWNERS ASSOC\w*|COUNCIL|NJ TRANSIT|COMMISSION)\b")

ORDINALS = {"FIRST": "1ST", "SECOND": "2ND", "THIRD": "3RD", "FOURTH": "4TH", "FIFTH": "5TH", "SIXTH": "6TH",
            "SEVENTH": "7TH", "EIGHTH": "8TH", "NINTH": "9TH", "TENTH": "10TH", "ELEVENTH": "11TH",
            "TWELFTH": "12TH", "THIRTEENTH": "13TH", "FOURTEENTH": "14TH", "FIFTEENTH": "15TH", "SIXTEENTH": "16TH"}
SUFFIX = {"STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "BOULEVARD": "BLVD", "ROAD": "RD", "PLACE": "PL",
          "TERRACE": "TER", "DRIVE": "DR", "COURT": "CT", "LANE": "LN", "PARKWAY": "PKWY", "HIGHWAY": "HWY",
          "SQUARE": "SQ", "PLAZA": "PLZ"}
UNIT = re.compile(r"\s*(#\s*\S+|\b(APT|UNIT|STE|SUITE|FL|FLOOR|RM|PH)\b\.?\s*\S*)\s*$")


CARE_OF = re.compile(r"\s+(%|C/O|C\\O|ATTN:?)\s*|\s+C O\s+")


def split_care_of(name):
    """'450 SEVENTH LLC % HOTHEM' -> ('450 SEVENTH LLC', 'HOTHEM')."""
    parts = CARE_OF.split((name or "").upper(), maxsplit=1)
    return parts[0], (parts[-1] if len(parts) > 1 else "")


def norm_name(name, keep_care_of=False):
    if not keep_care_of:
        name = split_care_of(name)[0]
    s = re.sub(r"[.,'&/]+", " ", (name or "").upper())
    s = re.sub(r"\bL\s+L\s+C\b", "LLC", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_street(addr):
    """'121-23 MAIN ST #310' -> ({121, 122, 123}, 'MAIN ST'). Returns (set(), '') if no house number."""
    s = re.sub(r"[.,]", " ", (addr or "").upper())
    s = UNIT.sub("", re.sub(r"\s+", " ", s).strip())
    m = re.match(r"^(\d+)(?:\s*-\s*(\d+))?[A-Z]?\s+(.*)$", s)
    if not m:
        return set(), ""
    lo, hi_raw, street = int(m.group(1)), m.group(2), m.group(3)
    numbers = {lo}
    if hi_raw:
        hi = int(hi_raw)
        if hi < lo:  # '121-23' means 121..123
            hi = int(str(lo)[: len(str(lo)) - len(hi_raw)] + hi_raw)
        if 0 <= hi - lo <= 20:
            numbers = set(range(lo, hi + 1))
    words = [ORDINALS.get(w, SUFFIX.get(w, w)) for w in street.split()]
    words = UNIT.sub("", " ".join(words)).split()
    return numbers, " ".join(words)


def same_address(property_location, mailing_address):
    p_nums, p_street = parse_street(property_location)
    m_nums, m_street = parse_street(mailing_address)
    if not (p_nums and m_nums and p_street and m_street):
        return False
    # compare street name without the suffix, so '1021 GRAND' matches '1021 GRAND ST'
    strip = lambda s: re.sub(r"\s(ST|AVE|BLVD|RD|PL|TER|DR|CT|LN|PKWY|HWY|SQ|PLZ)$", "", s)  # noqa: E731
    return bool(p_nums & m_nums) and strip(p_street) == strip(m_street)


def portfolio_sizes(rows):
    """{row index: parcels held by the same owner name, or same mailing address for entities}."""
    by_name = Counter(norm_name(r.get("owner_name")) for r in rows if r.get("owner_name"))
    def mail_key(r):
        return (re.sub(r"\s+", " ", (r.get("mailing_address") or "").upper()).strip(),
                (r.get("mailing_zip") or "")[:5])
    def care_of(r):
        return norm_name(split_care_of(r.get("owner_name"))[1], keep_care_of=True)

    entities = [r for r in rows if r.get("owner_name") and ENTITY.search(norm_name(r["owner_name"]))]
    by_mail = Counter(mail_key(r) for r in entities if r.get("mailing_address"))
    by_care_of = Counter(care_of(r) for r in entities if care_of(r))
    out = {}
    for i, r in enumerate(rows):
        name = norm_name(r.get("owner_name"))
        n = by_name.get(name, 0) if name else 0
        if name and ENTITY.search(name):
            if r.get("mailing_address"):
                n = max(n, by_mail.get(mail_key(r), 0))
            if care_of(r):
                n = max(n, by_care_of.get(care_of(r), 0))
        out[i] = n
    return out


def classify(row, portfolio):
    name = norm_name(row.get("owner_name"))
    if not name:
        return "unknown"
    if PUBLIC.search(name):
        return "public_nonprofit"
    if ENTITY.search(name):
        if portfolio >= CORPORATE_MIN_PARCELS or INSTITUTIONAL.search(name):
            return "corporate"
        return "small_llc"
    if TRUST.search(name):
        return "trust_estate"
    if same_address(row.get("property_location"), row.get("mailing_address")):
        return "owner_occupied"
    return "individual_investor"


def classify_all(rows):
    sizes = portfolio_sizes(rows)
    return [(classify(r, sizes[i]), sizes[i]) for i, r in enumerate(rows)]
