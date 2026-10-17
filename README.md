# Jersey City Property Tax Helper

A tool to help Jersey City and Hudson County homeowners see how their property taxes have
changed, how that compares with their neighbors and nearby towns, and how tax abatements work.

Status: **Phase 0 – data feasibility.** Only the data pipeline and quality checks exist so far.

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
