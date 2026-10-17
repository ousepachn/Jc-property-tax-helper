"""Download Hudson County parcels + MOD-IV attributes from the NJOGIS statewide composite.

Source: Parcels_Composite_NJ_WM FeatureServer (NJ Office of GIS). Owner names are
redacted at the source (Daniel's Law). Geometry is reduced to a lat/lon centroid.

Usage: python pipeline/fetch_njogis_parcels.py [--county HUDSON] [--out data/raw/njogis]
"""
import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

SERVICE = (
    "https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/"
    "Parcels_Composite_NJ_WM/FeatureServer/0"
)
PAGE_SIZE = 2000
DATE_FIELDS = {"PCLLASTUPD", "PCL_PBDATE"}
SKIP_FIELDS = {"OWNER_NAME", "Shape__Area", "Shape__Length"}


def get(url, params, retries=4):
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=120)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            return data
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2 ** (attempt + 1))


def to_iso(ms):
    if ms is None:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", default="HUDSON")
    ap.add_argument("--out", default="data/raw/njogis")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    layer = get(SERVICE, {"f": "json"})
    fields = [f["name"] for f in layer["fields"] if f["name"] not in SKIP_FIELDS]
    where = f"COUNTY='{args.county}'"
    total = get(f"{SERVICE}/query", {"where": where, "returnCountOnly": "true", "f": "json"})["count"]

    out_csv = out_dir / f"parcels_{args.county.lower()}.csv"
    rows = 0
    with out_csv.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields + ["LAT", "LON"])
        writer.writeheader()
        for offset in range(0, total, PAGE_SIZE):
            page = get(
                f"{SERVICE}/query",
                {
                    "where": where,
                    "outFields": ",".join(fields),
                    "orderByFields": "OBJECTID",
                    "resultOffset": offset,
                    "resultRecordCount": PAGE_SIZE,
                    "returnGeometry": "false",
                    "returnCentroid": "true",
                    "outSR": 4326,
                    "f": "json",
                },
            )
            for feat in page["features"]:
                row = feat["attributes"]
                for f in DATE_FIELDS:
                    row[f] = to_iso(row.get(f))
                c = feat.get("centroid") or {}
                row["LAT"], row["LON"] = c.get("y"), c.get("x")
                writer.writerow(row)
                rows += 1
            print(f"{rows}/{total}", flush=True)

    meta = {
        "source": SERVICE,
        "county": args.county,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "service_last_edit": to_iso(layer.get("editingInfo", {}).get("lastEditDate")),
        "expected_rows": total,
        "rows": rows,
    }
    (out_dir / f"parcels_{args.county.lower()}.meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
