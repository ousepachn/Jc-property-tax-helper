# Jersey City Property Tax Helper

A tool to help Jersey City and Hudson County homeowners see how their property taxes have
changed, how that compares with their neighbors and nearby towns, and how tax abatements work.

Status: **Phase 1 – data extraction.** State data pipeline, quality checks, and live billing-portal extraction
for Jersey City, Hoboken and Union City.

## Data pipeline

```
pip install -r requirements.txt

# 1. NJ parcel map + MOD-IV attributes for Hudson County (hosted NJOGIS service)
python pipeline/fetch_njogis_parcels.py --county HUDSON --out data/raw/njogis

# 2. State MOD-IV tax lists, one zip per year (statewide, ~270 MB each). Keep the Hudson file:
#    https://www.nj.gov/treasury/taxation/pdf/lpt/modiv-<YEAR>.zip  ->  data/raw/modiv/hudson_<YEAR>.txt
python pipeline/modiv.py data/raw/modiv/hudson_2026.txt data/interim/modiv_hudson_2026.csv

# 3. Official rates and averages -> data/raw/state/
#    GTRhistory.xlsx, <YEAR>AvgResStat.pdf from https://www.nj.gov/treasury/taxation/lpt/statdata.shtml

# 4. Actual Jersey City bills for a stratified sample (city's public tax inquiry)
python pipeline/sample_jc_bills.py data/interim/modiv_hudson_2026.csv data/interim/jc_bill_sample.csv

# 5. Quality / currency report -> data/interim/quality/
python pipeline/quality_report.py

python -m pytest tests
```

`data/raw/` is not committed (large, re-downloadable).

## Live billing portals (Jersey City, Hoboken, Union City)

| Town | Portal | Client |
|---|---|---|
| Jersey City (0906) | HLS Systems Property Tax Inquiry (JSON API) | `pipeline/portals/hls.py` |
| Hoboken (0905) | Edmunds WIPP (GWT-RPC) — its HLS page has no bill data | `pipeline/portals/wipp.py` |
| Union City (0910) | Edmunds WIPP (GWT-RPC) | `pipeline/portals/wipp.py` |

```
P="python pipeline/extract_bills.py"            # SQLite store: data/portal/bills.sqlite
$P index  --town union-city                     # 1. list every account (resumable)
$P fetch  --town union-city                     # 2. fetch bills for pending accounts (resumable)
$P status                                       # progress per town
$P export --out data/portal/export              # accounts.csv, bills.csv, annual.csv
python pipeline/validate_portal.py              # compare against the MOD-IV 2026 list
```

- Requests are sequential, 1 per second by default (`--interval`). Stop and re-run any time.
- Every bill gets a `category`: `property_tax` (regular, added, omitted), `appeal_adjustment`
  (tax court / county board / assessor), or `other` (payment bookkeeping, water/sewer, SID, hotel tax).
  Only `property_tax` should be used for "what did this property pay".
- Owner names and mailing addresses returned by the portals are dropped before storage.
- If Edmunds redeploys WIPP, calls fail with `//EX`; refresh `PERMUTATION`/`POLICY` in `wipp.py`
  from any request the page makes in a browser.

## Sources

| Source | What it has | How current |
|---|---|---|
| NJ Division of Taxation MOD-IV tax lists (`modiv-YYYY.zip`) | Every parcel: assessment, class, exemptions/abatement statute, last year's tax | List for year Y is certified in January of Y; its `last_year_tax` is tax year Y-1. Newest: 2026 list → 2025 taxes. |
| NJOGIS Parcels & MOD-IV composite (ArcGIS) | Parcel shapes/centroids joined to MOD-IV | Matches the **2025** list exactly (so taxes = 2024). Use for location only. |
| NJ General Tax Rates history (`GTRhistory.xlsx`) | Official rate per $100 by town, 1997-2025 | 2026 not yet published. |
| NJ Average Residential Statistics (`YYYYAvgResStat.pdf`) | Count, avg assessment, avg tax of class 2 homes by town | 2026 edition has no tax column yet. |
| Jersey City Property Tax Inquiry (HLS Systems) | Actual quarterly bills per account, incl. 2026 Q3/Q4 | Live. Queried one parcel at a time; owner names are never stored. |

## Privacy

Owner names are redacted at the state sources (Daniel's Law) and are never stored or displayed here.
Lookups are by address or block/lot only.
