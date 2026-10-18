"""Edmunds 'WIPP' public tax inquiry (Union City; also used by other NJ towns).

The page is a GWT app that talks GWT-RPC to {ROOT}/wipp/wipp. We replay two calls:
  taxBlqIdSearch(muni, startKey, "", true) -> 20 [key, location, key] rows starting at startKey
  getTaxAcct(muni, key)                    -> one account with assessments and quarterly bills

GWT-RPC responses are '//OK' + JSON array: [int payload..., [string table], flags, version].
Bills are located by their shape in the payload (amount, Integer, year, month, day, Day, label)
rather than by a full object schema, and checked against MOD-IV in validation. Header fields
(assessments, owner, mailing address) are read by position; see read_header().
"""
import json
import re

from .http import PoliteSession
from .models import Account, Bill, FetchResult, make_pin, pin_part

ROOT = "https://wipp.edmundsassoc.com/Wipp"
MODULE_BASE = f"{ROOT}/wipp/"
# From the deployed GWT permutation; if Edmunds redeploys, calls return //EX and these need refreshing
# (load the page in a browser and copy X-GWT-Permutation and the policy hash from any request).
PERMUTATION = "F5D343E3AC7C47E2FB2D45D6D2338A8D"
POLICY = "D5E8FE1926F7761CD5A2EA6F4F52F53E"
SERVICE = "wipp.client.WippService"
STRING_T = "java.lang.String/2004016611"
DUE_MONTH_TO_QUARTER = {2: 1, 5: 2, 8: 3, 11: 4}


class WippError(RuntimeError):
    pass


def rpc_body(method, args):
    """Build a GWT-RPC v7 request. args: list of ('S', str) or ('Z', bool)."""
    table = [MODULE_BASE, POLICY, SERVICE, method]
    index = {s: i + 1 for i, s in enumerate(table)}

    def ref(s):
        if s not in index:
            table.append(s)
            index[s] = len(table)
        return index[s]

    types = [ref(STRING_T) if kind == "S" else ref("Z") for kind, _ in args]
    values = [ref(v) if kind == "S" else (1 if v else 0) for kind, v in args]
    payload = [1, 2, 3, 4, len(args), *types, *values]
    return "|".join(["7", "0", str(len(table)), *table, *map(str, payload)]) + "|"


_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789$_"


def gwt_long(token):
    value = 0
    for ch in token:
        value = value * 64 + _B64.index(ch)
    return value - (1 << 64) if value >= (1 << 63) else value


def parse_response(text):
    if not text.startswith("//OK"):
        raise WippError(text[:300])
    # GWT emits JavaScript, not strict JSON: \xHH escapes, split string tables, and
    # 64-bit longs as single-quoted base-64 tokens ('A' = 0, 'fQA' = 8000) in the payload.
    body = re.sub(r"\\x([0-9A-Fa-f]{2})", r"\\u00\1", text[4:]).replace("].concat([", ",")
    split = body.find(',["')
    payload, rest = (body[:split], body[split:]) if split >= 0 else (body, "")
    payload = re.sub(r"'([A-Za-z0-9$_]+)'", lambda m: str(gwt_long(m.group(1))), payload)
    arr = json.loads(payload + rest)
    return arr[:-3], arr[-3]   # ints, strings


def parse_key(key):
    """'   39  01    9       C0602   ' -> (block '39.01', lot '9', qualifier 'C0602')."""
    k = key.ljust(29)
    return pin_part(k[0:5], k[5:9]), pin_part(k[9:14], k[14:18]), k[18:29].strip()


def parse_search(text):
    """[(key, location)] from a taxBlqIdSearch response."""
    ints, strings = parse_response(text)
    stream = list(reversed(ints))
    pos = 0

    def nxt():
        nonlocal pos
        pos += 1
        return stream[pos - 1]

    def read_string():
        t = nxt()
        return strings[nxt() - 1] if t > 0 else None

    rows = []
    if nxt() <= 0:
        return rows
    for _ in range(nxt()):
        nxt()                      # inner ArrayList type
        n = nxt()
        vals = [read_string() for _ in range(n)]
        rows.append((vals[0], (vals[1] or "").strip()))
    return rows


def _money(s):
    s = (s or "").strip().replace(",", "")
    return int(s) if s.isdigit() else None


HEADER_FIELDS = 17


def read_header(ints, strings, muni):
    """Read the TaxAcct header fields positionally.

    GWT reads the payload from the end, so the account's leading fields sit just before the
    municipality reference. Observed order (walking backwards from it):
      0 unknown, 1 exempt value, 2 improvement, 3 Day(as-of), 4 land, 5 Day(last payment),
      6 ArrayList, 7 net taxable, 8-10 blank, 11 (object), 12 mailing city/state, 13 owner name,
      14 mailing address, 15 mailing address line 2, 16 mailing zip.
    Returns a dict (improvement, land, net, owner_name, mailing_*) or None if the layout differs.
    """
    try:
        muni_ref = strings.index(muni) + 1
        day_t = next(i for i, s in enumerate(strings, 1) if s.startswith("wipp.client.Day/"))
        list_t = strings.index("java.util.ArrayList/4159755760") + 1
    except (ValueError, StopIteration):
        return None
    p = next((i for i in range(len(ints) - 1) if ints[i] == muni_ref and ints[i + 1] in (-8, 0)), None)
    if p is None:
        return None
    fields, i = [], p - 1
    while i >= 0 and len(fields) < HEADER_FIELDS:
        t = ints[i]
        if t == day_t:
            fields.append(("day", None))
            i -= 4
        elif t == list_t:
            if ints[i - 1] != 0:
                return None
            fields.append(("list", None))
            i -= 2
        else:
            fields.append(("str", strings[t - 1] if 0 < t <= len(strings) else None))
            i -= 1
    if len(fields) < 8:
        return None
    fields += [("str", None)] * (HEADER_FIELDS - len(fields))

    def is_(n, kind):  # a null object is a single 0 token, read as ("str", None)
        return fields[n][0] == kind or fields[n] == ("str", None)

    if not (is_(3, "day") and is_(5, "day") and is_(6, "list")):
        return None
    improvement, land, net = _money(fields[2][1]), _money(fields[4][1]), _money(fields[7][1])
    if None in (improvement, land, net) or improvement + land != net:
        return None

    def text(n):
        v = fields[n][1] if fields[n][0] == "str" else None
        return (v or "").strip() or None

    return {
        "improvement": improvement, "land": land, "net": net,
        "mailing_city_state": text(12), "owner_name": text(13), "mailing_address": text(14),
        "mailing_address2": text(15), "mailing_zip": text(16),
    }


def _bill_slots(ints, b, int_t, n=3):
    """Read the n Integer-or-reference fields just left of the billed amount at ints[b].

    Observed layout (forward order): ..., slot3, slot2(balance), slot1(interest), billed, Integer, Y, M, D, Day.
    A slot is either (value, Integer-type) or a single negative back-reference. Back-references
    only occur for values GWT shares between objects, which in practice is Integer 0, so they read as 0.
    """
    slots, j = [], b - 1
    for _ in range(n):
        if j >= 1 and ints[j] == int_t:
            slots.append(ints[j - 1])
            j -= 2
        else:
            slots.append(0)
            j -= 1
    return slots


def parse_account(text, key, county_district, source):
    ints, strings = parse_response(text)
    try:
        int_t = strings.index("java.lang.Integer/3438268394") + 1
        day_t = next(i for i, s in enumerate(strings, 1) if s.startswith("wipp.client.Day/"))
    except (ValueError, StopIteration):
        int_t = day_t = None

    block, lot, qual = parse_key(key)
    pin = make_pin(county_district, block, lot, qual)
    acct = Account(county_district=county_district, account_id=key, pin=pin)

    header = read_header(ints, strings, county_district)
    if header:
        acct.improvement_value, acct.land_value, acct.net_taxable = header["improvement"], header["land"], header["net"]
        for f in ("owner_name", "mailing_address", "mailing_address2", "mailing_city_state", "mailing_zip"):
            setattr(acct, f, header[f])
    cls = [s.strip() for s in strings if re.fullmatch(r"\s?\d{1,2}[A-F]?\s?", s or "") and len(s) == 3]
    if cls:
        acct.property_class = cls[0]

    bills = []
    if int_t and day_t:
        for i in range(len(ints) - 7):
            amount, t, y, m, d, dt, label = ints[i:i + 7]
            if t == int_t and dt == day_t and 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31 and 0 < label <= len(strings):
                year_label = strings[label - 1].strip()
                tax_year = int(year_label) if year_label.isdigit() else y
                interest, balance, _ = _bill_slots(ints, i, int_t)
                bills.append(Bill(
                    pin=pin, account_id=acct.account_id, tax_year=tax_year,
                    quarter=DUE_MONTH_TO_QUARTER.get(m), due_date=f"{y:04d}-{m:02d}-{d:02d}",
                    # negative rows are credits/refunds (e.g. appeal judgments), not bills
                    kind="tax" if amount >= 0 else "credit", amount=amount / 100, source=source,
                    balance=balance / 100, interest=interest / 100,
                ))
    bills.sort(key=lambda b: b.due_date)
    acct.total_due = round(sum((b.balance or 0) + (b.interest or 0) for b in bills if b.amount > 0), 2)
    acct.status = "done" if bills else "no_bills"
    return FetchResult(acct, bills, raw=text)


class WippPortal:
    def __init__(self, wippid, county_district=None, session=None):
        self.wippid = wippid
        self.county_district = county_district or wippid
        self.source = f"wipp:{wippid}"
        self.http = session or PoliteSession()

    def _call(self, method, args):
        r = self.http.post(f"{ROOT}/wipp/wipp", data=rpc_body(method, args).encode("utf-8"), headers={
            "Content-Type": "text/x-gwt-rpc; charset=UTF-8",
            "X-GWT-Permutation": PERMUTATION,
            "X-GWT-Module-Base": MODULE_BASE,
        })
        return r.text

    def search(self, start_key):
        return parse_search(self._call("taxBlqIdSearch", [("S", self.wippid), ("S", start_key), ("S", ""), ("Z", True)]))

    def iter_accounts(self, start_key="", max_pages=None):
        """Yield (page_start_key, Account) for every tax account, walking the key order."""
        seen, key, pages = set(), start_key, 0
        while True:
            rows = self.search(key)
            pages += 1
            new = [(k, loc) for k, loc in rows if k not in seen]
            for k, loc in new:
                seen.add(k)
                block, lot, qual = parse_key(k)
                yield key, Account(county_district=self.county_district, account_id=k,
                                   pin=make_pin(self.county_district, block, lot, qual), property_location=loc)
            if not new or (max_pages and pages >= max_pages):
                return
            key = rows[-1][0]

    def fetch(self, account):
        key = account.account_id   # raw, space-padded 29-char block/lot/qualifier key
        return self.parse_raw(self._call("getTaxAcct", [("S", self.wippid), ("S", key)]), account)

    def parse_raw(self, raw, account):
        """Parse a stored getTaxAcct response (no network)."""
        res = parse_account(raw, account.account_id, self.county_district, self.source)
        res.account.property_location = account.property_location
        return res
