"""Edmunds 'WIPP' public tax inquiry (Union City; also used by other NJ towns).

The page is a GWT app that talks GWT-RPC to {ROOT}/wipp/wipp. We replay two calls:
  taxBlqIdSearch(muni, startKey, "", true) -> 20 [key, location, key] rows starting at startKey
  getTaxAcct(muni, key)                    -> one account with assessments and quarterly bills

GWT-RPC responses are '//OK' + JSON array: [int payload..., [string table], flags, version].
They are decoded with GwtReader using the field layouts in SCHEMAS (taken from the app's own
JavaScript), and checked against MOD-IV in validation.
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
    """'   88  02    7       C0310   ' -> (block '88.02', lot '7', qualifier 'C0310')."""
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
    return int(s) if s.lstrip("-").isdigit() else None


def _text(s):
    return (s or "").strip() or None


# Field layouts of the GWT classes that can appear in a getTaxAcct response, in the order the
# client reads them. Extracted from the deployed WIPP JavaScript (each class's FieldSerializer):
# (obfuscated field name, kind). Field meanings below come from how the page renders them.
SCHEMAS = {
    'TaxAcct': [('a', 'string'), ('b', 'string'), ('c', 'string'), ('d', 'string'), ('e', 'prim'), ('f', 'string'), ('g', 'object'), ('i', 'string'), ('j', 'prim'), ('k', 'string'), ('n', 'string'), ('o', 'object'), ('p', 'string'), ('q', 'object'), ('r', 'object'), ('s', 'string'), ('t', 'string'), ('u', 'string'), ('v', 'string'), ('w', 'prim'), ('A', 'string'), ('B', 'string'), ('C', 'string'), ('D', 'string'), ('F', 'string'), ('G', 'string'), ('H', 'string'), ('I', 'string'), ('J', 'long'), ('K', 'prim'), ('L', 'prim'), ('M', 'object'), ('N', 'object'), ('O', 'string'), ('P', 'string'), ('Q', 'string'), ('R', 'string'), ('S', 'prim'), ('T', 'prim'), ('U', 'prim'), ('V', 'object'), ('W', 'prim'), ('X', 'prim')],
    'LienAcct': [('a', 'string'), ('b', 'string'), ('c', 'string'), ('d', 'prim'), ('e', 'string'), ('f', 'string'), ('g', 'prim'), ('i', 'prim'), ('j', 'prim'), ('k', 'prim'), ('n', 'object'), ('o', 'prim'), ('p', 'string')],
    'SpAssmtAcct': [('a', 'string'), ('b', 'string'), ('c', 'string'), ('d', 'prim'), ('e', 'string'), ('f', 'object'), ('g', 'prim'), ('i', 'object'), ('j', 'prim'), ('k', 'object'), ('n', 'prim'), ('o', 'prim'), ('p', 'string'), ('q', 'prim'), ('r', 'prim'), ('s', 'prim')],
    'SpChargesAcct': [('a', 'string'), ('b', 'prim'), ('c', 'string'), ('d', 'string'), ('e', 'string'), ('f', 'prim'), ('g', 'prim'), ('i', 'prim'), ('j', 'prim'), ('k', 'prim'), ('n', 'object'), ('o', 'object'), ('p', 'prim'), ('q', 'prim')],
    'Day': [('a', 'prim'), ('b', 'prim'), ('c', 'prim')],
}

# Classes the client also sends but whose fields we don't use (utility, PILOT and NNJ lien accounts).
# Only their layout matters, to keep the reader aligned: s = string, p = primitive, o = object.
_POSITIONAL = {
    'UtilAcct': 'spssspspooppoppopoppspoppppooooooooooooppppppppppppppppppppppppppppppppppppppppppppppppoooooooooooopppppppppppppppppppppppppppoospspooppopposppoppppoooooooooooopppppppppppppppppppppppppppppppppppppppppppppooooooooopppppppppppppppppppppssssssspsoopspooppoppopoppsppoppppooooooooooooppppppppppppppppppppppppppppppppppppppppppppppppoooooooooooopppppppppppppppppppppppppppppspooppoppopoppspoppppooooooooooooppppppppppppppppppppppppppppppppppppppppppppppppooooooooooooppppppppppppppppppppppppppp',
    'PilotAcct': 'sssspsospssosoospsssssssspppoosssspppop',
    'NNJLienAcct': 'sppssppsppopsssssssspps',
}
_KIND = {"s": "string", "p": "prim", "o": "object"}
SCHEMAS.update({cls: [(f"f{i}", _KIND[k]) for i, k in enumerate(kinds)] for cls, kinds in _POSITIONAL.items()})


class GwtReader:
    """Minimal GWT-RPC v7 object-stream reader for the classes in SCHEMAS."""

    def __init__(self, ints, strings):
        self.stream, self.pos, self.strings, self.seen = list(reversed(ints)), 0, strings, []

    def int(self):
        self.pos += 1
        return self.stream[self.pos - 1]

    def string(self):
        i = self.int()
        return self.strings[i - 1] if i > 0 else None

    def object(self):
        token = self.int()
        if token == 0:
            return None
        if token < 0:
            return self.seen[-token - 1]
        sig = self.strings[token - 1]
        name = sig.split("/")[0].rsplit(".", 1)[-1]
        idx = len(self.seen)
        self.seen.append(None)
        if name == "ArrayList":
            obj = []
            self.seen[idx] = obj
            obj.extend(self.object() for _ in range(self.int()))
        elif name in ("Integer", "Long", "Short", "Byte", "Character", "Boolean"):
            obj = self.int()
        elif name == "String":
            obj = self.string()
        elif name in SCHEMAS:
            obj = {"_type": name}
            self.seen[idx] = obj
            for field, kind in SCHEMAS[name]:
                obj[field] = self.string() if kind == "string" else self.object() if kind == "object" else self.int()
        else:
            raise WippError(f"unknown GWT type in response: {sig}")
        self.seen[idx] = obj
        return obj


def _day(d):
    """Day objects are (day, month, year); 1000-01-01 is the portal's 'no date'."""
    if not d or d.get("c", 0) < 1900:
        return None
    return f"{d['c']:04d}-{d['b']:02d}-{d['a']:02d}"


def _cents(v):
    return None if v is None else v / 100


def read_tax_acct(text):
    ints, strings = parse_response(text)
    acct = GwtReader(ints, strings).object()
    if not isinstance(acct, dict) or acct.get("_type") != "TaxAcct":
        raise WippError("response is not a TaxAcct")
    return acct


def parse_account(text, key, county_district, source):
    """Parse a getTaxAcct response.

    TaxAcct fields used (see SCHEMAS): e bankruptcy flag ('Y'), g bills by year, k exempt value,
    n improvement, p land, s net taxable, r liens (LienAcct list), A mailing city/state, B owner,
    C/D mailing address lines, F mailing zip, H property class, K lien flag ('L'),
    U tax-sale flag ('Y'). Each bill row is a 9-element list:
    [year label, due Day, billed, interest, balance, ?, type, Day, ?] with amounts in cents.
    """
    t = read_tax_acct(text)
    block, lot, qual = parse_key(key)
    pin = make_pin(county_district, block, lot, qual)
    acct = Account(county_district=county_district, account_id=key, pin=pin)

    acct.improvement_value, acct.land_value, acct.net_taxable = _money(t["n"]), _money(t["p"]), _money(t["s"])
    acct.property_class = (t.get("H") or "").strip()
    acct.owner_name, acct.mailing_city_state = _text(t["B"]), _text(t["A"])
    acct.mailing_address, acct.mailing_address2, acct.mailing_zip = _text(t["C"]), _text(t["D"]), _text(t["F"])
    acct.bankruptcy = t["e"] == ord("Y")
    acct.pending_tax_sale = t["U"] == ord("Y")
    liens = [lien for lien in (t["r"] or []) if isinstance(lien, dict)]
    acct.liens = [{
        "certificate": _text(lien["b"]), "sale_date": _day(lien["n"]), "holder": _text(lien["e"]),
        "sale_amount": _cents(lien["k"]), "subsequent_charges": _cents(lien["o"]),
    } for lien in liens]
    acct.lien_count = len(liens) or (1 if t["K"] == ord("L") else 0)
    acct.lien_open_balance = round(sum((x["sale_amount"] or 0) + (x["subsequent_charges"] or 0)
                                       for x in acct.liens), 2) if liens else None

    bills = []
    for year in t["g"] or []:
        for row in year or []:
            if not isinstance(row, list) or len(row) < 5 or not row[1]:
                continue
            label, due, billed, interest, balance = row[:5]
            due_date = _day(due)
            if due_date is None or billed is None:
                continue
            tax_year = int(label) if (label or "").strip().isdigit() else int(due_date[:4])
            bills.append(Bill(
                pin=pin, account_id=key, tax_year=tax_year,
                quarter=DUE_MONTH_TO_QUARTER.get(int(due_date[5:7])), due_date=due_date,
                # negative rows are credits/refunds (e.g. appeal judgments), not bills
                kind="tax" if billed >= 0 else "credit", amount=billed / 100, source=source,
                balance=_cents(balance or 0), interest=_cents(interest or 0),
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
