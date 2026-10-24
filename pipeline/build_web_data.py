"""Build the data files for the Jersey City property tax web page (web/).

  python pipeline/build_web_data.py --export data/portal/export/hls --out web/data

Inputs: the hls export (accounts.csv, annual.csv, bills.csv.gz), the MOD-IV lists in
data/interim/modiv_hudson_<year>.csv and NJOGIS parcel centroids. Output contains public tax-roll
fields only (address, class, assessments, bills, recorded sales): no owner names or mailing
addresses, and no delinquency data.

Writes:
  meta.json            rates by year, city ratios, build date, field order
  index.json           one row per property, for search and comparables:
                       [pin, address, unit, type, assessed 2026, tax 2025, tax 2026, shard]
  shards/<n>.json      per-property detail, keyed by pin (loaded on demand)
"""
import argparse
import json
import math
import re
import sys
import zlib
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_delinquency import property_type  # noqa: E402

CD = "0906"
YEARS = list(range(2019, 2027))
MODIV_YEARS = list(range(2021, 2027))
# Jersey City general tax rate per $100 of assessed value (NJ GTR history; 2026 from the 2026 bills)
RATES = {2019: 1.540, 2020: 1.610, 2021: 1.604, 2022: 2.118, 2023: 2.247, 2024: 2.233, 2025: 2.335, 2026: 2.657}
N_SHARDS = 96
KM_PER_DEG = 111.32
NEAR_KM, FAR_KM = 0.8, 1.6        # about half a mile, then a mile
MAX_COMPS, MIN_COMPS, SHOW_COMPS = 25, 8, 12   # medians use up to 25; the page lists 12
SALES_FROM = pd.Timestamp("2024-07-01")
TYPE_CODES = {"condo": "condo", "single_family": "1fam", "two_to_four_family": "2-4fam",
              "home_units_unknown": "home", "apartment_5plus": "apt", "commercial": "comm",
              "vacant_land": "land", "condo_parking_or_land": "cpark", "exempt": "exempt",
              "no_class_on_file": "none", "other": "other"}


def shard_of(pin):
    return zlib.crc32(pin.encode()) % N_SHARDS


def num(s):
    return pd.to_numeric(s, errors="coerce")


def load_modiv(path):
    m = pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    return m[m.county_district == CD]


def unit_of(pin):
    parts = pin.split("_")
    return parts[3] if len(parts) > 3 else ""


def tidy_address(s):
    s = re.sub(r"\s+", " ", (s or "").strip()).rstrip(".")
    s = s.title().replace("Mc ", "Mc").replace(" St.", " St").replace(" Ave.", " Ave")
    return re.sub(r"\bAv$", "Ave", s)


def lot_area_sqft(desc, acres):
    """Lot area from the tax list: calculated acreage when present, else a plain 'W X D' dimension."""
    if acres and acres > 0:
        return round(acres * 43560)
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*X\s*(\d+(?:\.\d+)?)\s*", desc or "")
    return round(float(m.group(1)) * float(m.group(2))) if m else None


def lot_and_exemptions(r):
    """Fields an owner can check against their property (MOD-IV 2026)."""
    out = {}
    area = lot_area_sqft(r.land_description.strip(), pd.to_numeric(r.calculated_acreage, errors="coerce"))
    if area:
        out["lotsf"] = area
    for key, col in (("zn", "zoning"), ("cls", "property_class"), ("fac", "facility_name")):
        if r[col].strip():
            out[key] = r[col].strip()
    dw = pd.to_numeric(r.no_of_dwellings, errors="coerce")
    if dw and dw > 0:
        out["dw"] = int(dw)
    ded, sen, vet = (int(pd.to_numeric(r[c], errors="coerce") or 0) for c in ("deduction_amount", "senior_citizens_cnt", "veterans_cnt"))
    if ded or sen or vet:
        out["ded"] = [ded, sen, vet]
    ex_amt = sum(int(pd.to_numeric(r[f"exemption_amt_{k}"], errors="coerce") or 0) for k in range(1, 5))
    if r.exempt_statute.strip() or ex_amt:
        out["ex"] = [r.exempt_statute.strip(), ex_amt]
    return out


class Grid:
    """Nearest-neighbour search over a subset of points, bucketed in ~0.4 km cells (no scipy needed)."""

    def __init__(self, xs, ys, members, cell=0.4):
        self.cell, self.xs, self.ys = cell, xs, ys
        cells = defaultdict(list)
        for i in members:
            if not math.isnan(xs[i]):
                cells[(int(xs[i] // cell), int(ys[i] // cell))].append(i)
        self.cells = {k: np.array(v) for k, v in cells.items()}

    def within(self, x, y, km):
        """Indices within km of (x, y), nearest first."""
        r = int(km // self.cell) + 1
        cx, cy = int(x // self.cell), int(y // self.cell)
        parts = [self.cells[k] for gx in range(cx - r, cx + r + 1) for gy in range(cy - r, cy + r + 1)
                 if (k := (gx, gy)) in self.cells]
        if not parts:
            return np.array([], dtype=int), np.array([])
        idx = np.concatenate(parts)
        d = np.hypot(self.xs[idx] - x, self.ys[idx] - y)
        keep = d <= km
        idx, d = idx[keep], d[keep]
        order = np.argsort(d, kind="stable")
        return idx[order], d[order]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True, help="hls export folder (accounts.csv, annual.csv, bills.csv.gz)")
    ap.add_argument("--modiv-dir", default="data/interim")
    ap.add_argument("--parcels", default="data/raw/njogis/parcels_hudson.csv")
    ap.add_argument("--city-ratio", type=float, help="official 2026 average ratio (as a fraction, e.g. 0.7)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    exp, out = Path(args.export), Path(args.out)
    (out / "shards").mkdir(parents=True, exist_ok=True)

    acc = pd.read_csv(exp / "accounts.csv", dtype=str, low_memory=False).fillna("")
    acc = acc[(acc.county_district == CD) & acc.status.isin(["done", "no_bills"])]
    acc = acc[["pin", "account_id", "property_location", "property_class", "land_value", "improvement_value", "net_taxable"]]
    acc = acc.drop_duplicates("pin").reset_index(drop=True)

    # MOD-IV: attributes from 2026, assessments by year
    m26 = load_modiv(Path(args.modiv_dir) / "modiv_hudson_2026.csv").drop_duplicates("pin").set_index("pin")
    assess = {}
    for y in MODIV_YEARS:
        p = Path(args.modiv_dir) / f"modiv_hudson_{y}.csv"
        if p.exists():
            m = load_modiv(p).drop_duplicates("pin")
            assess[y] = dict(zip(m.pin, num(m.net_value)))
    units = num(m26.no_of_dwellings.str.strip())
    units = units.where(units > 0, num(m26.building_description.str.extract(r"(\d+)U")[0]))
    dwell = units.to_dict()

    # coordinates: parcel centroid, else the base lot (condo units), else the block's mean
    g = pd.read_csv(args.parcels, usecols=["PAMS_PIN", "LAT", "LON"], dtype={"PAMS_PIN": str})
    g = g[g.PAMS_PIN.str.startswith(CD + "_")].dropna()
    coord = {p: (la, lo) for p, la, lo in zip(g.PAMS_PIN, g.LAT, g.LON)}
    base = defaultdict(list)
    block = defaultdict(list)
    for p, c in coord.items():
        base["_".join(p.split("_")[:3])].append(c)
        block[p.split("_")[1]].append(c)
    def locate(pin):
        if pin in coord:
            return coord[pin]
        for key, table in (("_".join(pin.split("_")[:3]), base), (pin.split("_")[1], block)):
            if table.get(key):
                pts = table[key]
                return (sum(c[0] for c in pts) / len(pts), sum(c[1] for c in pts) / len(pts))
        return (float("nan"), float("nan"))
    lat0 = 40.72
    ll = [locate(p) for p in acc.pin]
    acc["x"] = [lo * KM_PER_DEG * math.cos(math.radians(lat0)) for _, lo in ll]
    acc["y"] = [la * KM_PER_DEG for la, _ in ll]

    # annual taxes
    an = pd.read_csv(exp / "annual.csv", dtype={"pin": str})
    an = an[an.pin.isin(set(acc.pin))]
    tax = {y: dict(zip(d.pin, d.property_tax_billed)) for y, d in an.groupby("tax_year")}
    adj = an[an.appeal_adjustments.abs() > 1].groupby("pin").apply(
        lambda d: [[int(y), round(v)] for y, v in zip(d.tax_year, d.appeal_adjustments)], include_groups=False).to_dict()

    # quarterly property-tax bills 2025 .. 2027 (2027 = estimated first half, already billed)
    b = pd.read_csv(exp / "bills.csv.gz", dtype={"pin": str},
                    usecols=["pin", "tax_year", "quarter", "category", "amount", "due_date"])
    b = b[(b.category == "property_tax") & (b.tax_year >= 2025) & b.quarter.between(1, 4)]
    q = b.groupby(["pin", "tax_year", "quarter"]).amount.sum().round(0)
    quarters = defaultdict(lambda: [None] * 12)
    for (pin, y, qq), v in q.items():
        if 2025 <= y <= 2027:
            quarters[pin][(y - 2025) * 4 + qq - 1] = int(v)

    # property type, assessed values, comparable pools
    acc["dw"] = acc.pin.map(dwell)
    acc["type"] = [property_type(p, c, None if pd.isna(d) else int(d))
                   for p, c, d in zip(acc.pin, acc.property_class, acc.dw)]
    acc["av"] = num(acc.net_taxable).fillna(0)
    acc["t25"] = acc.pin.map(tax.get(2025, {}))
    acc["t26"] = acc.pin.map(tax.get(2026, {}))
    acc["a25"] = acc.pin.map(assess.get(2025, {}))

    # recorded sales (MOD-IV 2026 deed date/price), arm's-length heuristic: price > $50k and
    # assessment/price within 0.35..1.6
    sales = m26[["deed_date", "sale_price"]].copy()
    sales["dd"] = pd.to_datetime(sales.deed_date, format="%m%d%y", errors="coerce")
    sales["sp"] = num(sales.sale_price)
    sales = sales[(sales.dd >= SALES_FROM) & (sales.dd <= pd.Timestamp(date.today())) & (sales.sp > 50000)]
    sale = {p: (d, sp) for p, d, sp in zip(sales.index, sales.dd, sales.sp)}

    ratios = []
    for p, (d, sp) in sale.items():
        av = assess.get(2026, {}).get(p)
        if av and 0.35 <= av / sp <= 1.6 and m26.at[p, "property_class"] == "2":
            ratios.append(av / sp)
    city_sales_ratio = float(np.median(ratios)) if ratios else None

    pins, types = acc.pin.tolist(), acc.type.tolist()
    n = len(pins)
    xs, ys, avs = acc.x.to_numpy(float), acc.y.to_numpy(float), acc.av.to_numpy(float)
    land, impr = num(acc.land_value).fillna(0).astype(int).tolist(), num(acc.improvement_value).fillna(0).astype(int).tolist()
    T = np.array([[tax.get(y, {}).get(p, np.nan) for p in pins] for y in YEARS], dtype=float)
    a26_of = assess.get(2026, {})
    bdesc, ldesc = m26.building_description.str.strip().to_dict(), m26.land_description.str.strip().to_dict()
    built = num(m26.year_constructed).to_dict()
    details = {p: lot_and_exemptions(r) for p, r in m26.iterrows()}
    acct_no = acc.account_id.tolist()

    by_type = defaultdict(list)
    for i, t in enumerate(types):
        if avs[i] > 0:
            by_type[t].append(i)
    grids = {t: Grid(xs, ys, members) for t, members in by_type.items()}
    # sale comparables: recorded sale that looks arm's-length (see above)
    sold = [i for i, p in enumerate(pins) if p in sale and a26_of.get(p) and 0.35 <= a26_of[p] / sale[p][1] <= 1.6]
    sold_by_type = defaultdict(list)
    for i in sold:
        sold_by_type[types[i]].append(i)
    sale_grids = {t: Grid(xs, ys, members) for t, members in sold_by_type.items()}

    shards = defaultdict(dict)
    index_rows = []
    for i, pin in enumerate(pins):
        t, av = types[i], avs[i]
        history = [None if np.isnan(T[k, i]) else round(T[k, i]) for k in range(len(YEARS))]
        a_hist = [None if pd.isna(assess.get(y, {}).get(pin, np.nan)) else int(assess[y][pin]) for y in MODIV_YEARS]
        rec = {"h": history, "a": a_hist, "q": quarters[pin] if pin in quarters else None, "land": land[i], "impr": impr[i]}
        if pin in adj:
            rec["adj"] = adj[pin]
        rec["acct"] = acct_no[i]
        if not math.isnan(xs[i]):
            rec["ll"] = [round(ll[i][0], 6), round(ll[i][1], 6)]
        if pin in bdesc:
            rec["bd"], rec["lot"] = bdesc[pin], ldesc[pin]
            rec.update(details[pin])
            yb = built.get(pin)
            if yb and 1700 < yb <= 2027:
                rec["yb"] = int(yb)
        if pin in sale:
            rec["sale"] = [sale[pin][0].strftime("%Y-%m-%d"), int(sale[pin][1])]
        # comparables: same type, assessed within 2/3..1.5x, nearest first
        if not math.isnan(xs[i]) and av > 0 and t in grids and t not in ("exempt", "no_class_on_file", "other"):
            for km in (NEAR_KM, FAR_KM):
                cand, _ = grids[t].within(xs[i], ys[i], km)
                r = avs[cand] / av
                cand = cand[(cand != i) & (r >= 0.67) & (r <= 1.5)]
                if len(cand) >= MIN_COMPS or km == FAR_KM:
                    comps = cand[:MAX_COMPS]
                    break
            if len(comps):
                rec["c"] = [pins[j] for j in comps[:SHOW_COMPS]]
                rec["cn"] = int(len(comps))
                sub = T[:, comps]
                cnt = (~np.isnan(sub)).sum(axis=1)
                with np.errstate(all="ignore"):
                    med = np.nanmedian(np.where(cnt[:, None] > 0, sub, 0), axis=1)
                rec["cm"] = [round(float(m)) if c >= 3 else None for m, c in zip(med, cnt)]
                rec["cr"] = km
            if t in sale_grids:
                cand, dist = sale_grids[t].within(xs[i], ys[i], FAR_KM)
                keep = [(j, dd) for j, dd in zip(cand, dist) if j != i and 0.67 <= a26_of[pins[j]] / av <= 1.5][:8]
                if keep:
                    rec["s"] = [[pins[j], sale[pins[j]][0].strftime("%Y-%m-%d"), int(sale[pins[j]][1]),
                                 int(a26_of[pins[j]]), round(float(dd), 2)] for j, dd in keep]
        sh = shard_of(pin)
        shards[sh][pin] = rec
        t25, t26, a25 = acc.at[i, "t25"], acc.at[i, "t26"], acc.at[i, "a25"]
        index_rows.append([pin, tidy_address(acc.at[i, "property_location"]), unit_of(pin), TYPE_CODES.get(t, t),
                           int(av), None if pd.isna(t25) else round(t25), None if pd.isna(t26) else round(t26),
                           None if pd.isna(a25) else int(a25), sh])

    for sh, recs in shards.items():
        (out / "shards" / f"{sh}.json").write_text(json.dumps(recs, separators=(",", ":")))
    (out / "index.json").write_text(json.dumps(index_rows, separators=(",", ":")))
    meta = {
        "built": date.today().isoformat(), "years": YEARS, "assessment_years": MODIV_YEARS, "rates": RATES,
        "index_fields": ["pin", "address", "unit", "type", "assessed_2026", "tax_2025", "tax_2026", "assessed_2025", "shard"],
        "city_ratio_official": args.city_ratio, "city_sales_ratio": round(city_sales_ratio, 3) if city_sales_ratio else None,
        "sales_used": len(ratios), "sales_from": SALES_FROM.strftime("%Y-%m-%d"), "n_shards": N_SHARDS,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    print(f"{len(index_rows)} properties, {len(shards)} shards, sales ratio {meta['city_sales_ratio']} from {len(ratios)} sales")


if __name__ == "__main__":
    main()
