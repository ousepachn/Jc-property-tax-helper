"""Parse NJ Division of Taxation MOD-IV fixed-width tax list files.

Layout: https://www.nj.gov/treasury/taxation/pdf/lpt/modivlayout.pdf (rev. 08/16/2012).
Positions below are 1-based inclusive, copied from that document.
"""
import csv
import sys
from pathlib import Path

HUDSON_MUNICIPALITIES = {
    "0901": "Bayonne",
    "0902": "East Newark",
    "0903": "Guttenberg",
    "0904": "Harrison",
    "0905": "Hoboken",
    "0906": "Jersey City",
    "0907": "Kearny",
    "0908": "North Bergen",
    "0909": "Secaucus",
    "0910": "Union City",
    "0911": "Weehawken",
    "0912": "West New York",
}

# (name, start, end, kind) - kind: str | int | money (S9(7)V99 overpunch) | acres (9(5)V9(4))
FIELDS = [
    ("county_district", 1, 4, "str"),
    ("block", 5, 13, "str"),
    ("lot", 14, 22, "str"),
    ("qualifier", 23, 33, "str"),
    ("record_id", 34, 35, "str"),
    ("transaction_date", 38, 43, "str"),
    ("property_class", 56, 58, "str"),
    ("property_location", 59, 83, "str"),
    ("building_description", 84, 98, "str"),
    ("land_description", 99, 118, "str"),
    ("calculated_acreage", 119, 127, "acres"),
    ("zoning", 168, 171, "str"),
    ("zip_code", 261, 269, "str"),
    ("deduction_amount", 274, 279, "int"),
    ("deed_date", 307, 312, "str"),
    ("sale_price", 313, 321, "int"),
    ("sale_assessment", 322, 330, "int"),
    ("no_of_dwellings", 351, 352, "str"),
    ("no_of_commercial_dw", 353, 354, "str"),
    ("epl_own", 360, 361, "str"),
    ("epl_use", 362, 363, "str"),
    ("epl_desc", 364, 366, "str"),
    ("exempt_initial_date", 367, 372, "str"),
    ("exempt_further_date", 373, 378, "str"),
    ("exempt_statute", 379, 390, "str"),
    ("facility_name", 391, 410, "str"),
    ("building_class_code", 411, 415, "str"),
    ("year_constructed", 416, 419, "str"),
    ("assessment_code", 420, 420, "str"),
    ("land_value", 421, 429, "int"),
    ("improvement_value", 430, 438, "int"),
    ("net_value", 439, 447, "int"),
    ("special_tax_codes", 448, 459, "str"),
    ("exemption_code_1", 460, 460, "str"),
    ("exemption_amt_1", 461, 468, "int"),
    ("exemption_code_2", 469, 469, "str"),
    ("exemption_amt_2", 470, 477, "int"),
    ("exemption_code_3", 478, 478, "str"),
    ("exemption_amt_3", 479, 486, "int"),
    ("exemption_code_4", 487, 487, "str"),
    ("exemption_amt_4", 488, 495, "int"),
    ("senior_citizens_cnt", 496, 499, "int"),
    ("veterans_cnt", 500, 503, "int"),
    ("census_tract", 551, 555, "str"),
    ("property_use_code", 560, 562, "str"),
    ("property_flags", 563, 572, "str"),
    ("last_year_tax", 601, 609, "money"),
    ("current_year_tax", 610, 618, "money"),
    ("non_municipal_half1", 619, 627, "money"),
    ("non_municipal_half2", 628, 636, "money"),
    ("municipal_half1", 637, 645, "money"),
    ("municipal_half2", 646, 654, "money"),
    ("non_municipal_half3", 655, 663, "money"),
    ("municipal_half3", 664, 672, "money"),
    ("bill_status_flag", 673, 673, "str"),
    ("estimated_qtr3_tax", 674, 682, "money"),
    ("prior_yr_net_value", 683, 691, "int"),
]

# COBOL zoned-decimal sign overpunch on the last digit.
_POS = {"{": 0, **{chr(ord("A") + i): i + 1 for i in range(9)}}
_NEG = {"}": 0, **{chr(ord("J") + i): i + 1 for i in range(9)}}


def parse_signed(raw, decimals=2):
    """Decode an overpunched signed number like '00126604H' -> 12660.48."""
    raw = raw.strip()
    if not raw:
        return None
    last = raw[-1]
    sign = 1
    if last in _POS:
        raw = raw[:-1] + str(_POS[last])
    elif last in _NEG:
        raw = raw[:-1] + str(_NEG[last])
        sign = -1
    if not raw.isdigit():
        return None
    return sign * int(raw) / (10 ** decimals)


def parse_int(raw):
    raw = raw.strip()
    return int(raw) if raw.isdigit() else None


def parse_line(line):
    rec = {}
    for name, start, end, kind in FIELDS:
        raw = line[start - 1:end]
        if kind == "str":
            rec[name] = raw.strip()
        elif kind == "int":
            rec[name] = parse_int(raw)
        elif kind == "money":
            rec[name] = parse_signed(raw)
        elif kind == "acres":
            v = parse_int(raw)
            rec[name] = None if v is None else v / 10_000
    rec["municipality"] = HUDSON_MUNICIPALITIES.get(rec["county_district"], "")
    # Same format as PAMS_PIN in the NJOGIS parcel layer, e.g. 0901_7_1.01 or 0906_504_12_C0001
    rec["pin"] = "_".join(
        p for p in (
            rec["county_district"],
            norm_block_lot(line[4:13]),
            norm_block_lot(line[13:22]),
            rec["qualifier"],
        ) if p
    )
    return rec


def norm_block_lot(raw):
    """MOD-IV block/lot are a 5-digit base + 4-char suffix: '00001  01' -> '1.01', '00301' -> '301'."""
    base, suffix = raw[:5].strip(), raw[5:].strip()
    base = base.lstrip("0") or "0"
    return f"{base}.{suffix}" if suffix else base


def parse_file(path):
    with open(path, encoding="latin-1", newline="") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if len(line) < 700:
                line = line.ljust(700)
            yield parse_line(line)


def to_csv(src, dest):
    names = [f[0] for f in FIELDS] + ["municipality", "pin"]
    n = 0
    with open(dest, "w", newline="") as out:
        w = csv.DictWriter(out, fieldnames=names)
        w.writeheader()
        for rec in parse_file(src):
            w.writerow(rec)
            n += 1
    return n


if __name__ == "__main__":
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    print(to_csv(src, dest), "rows ->", dest)
