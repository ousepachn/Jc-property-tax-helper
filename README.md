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
- Owner names and mailing addresses are stored only with `--include-owners` (on `index`/`fetch`), and
  never for accounts the portal flags under Daniel's Law (N.J.S.A. 47:1B). `--keep-raw` also stores
  each portal response zlib-compressed in `raw_responses` (print one with `raw --pin <pin>`), which
  keeps payment history and full ledger history that the normalized `bills` table drops.
  `export --redact-owners` leaves the owner columns out.
- **Delinquency.** Each fetch also records, per account: `past_due_amount`, `past_due_bills`,
  `oldest_past_due`, `past_due_interest`, `total_due`, open tax-sale liens (`lien_count`,
  `lien_open_balance`), `redeemed_liens` (history) and the portal's own flags (`portal_delinquent`,
  `pending_tax_sale`, Jersey City only), summarized as `delinquency_level`:
  `current` / `1_quarter` / `2_3_quarters` / `4plus_quarters` / `lien`.
  A bill counts as past due when it still has a balance more than 10 days after its due date
  (N.J.S.A. 54:4-67 grace period), as of the moment the account was fetched (`fetched_at`).
  Bills before `--min-year` are not stored but still count. A property whose lien was bought by an
  investor shows $0 owed to the city; its debt is the lien's open balance. WIPP portals (Hoboken,
  Union City) report balances but not liens, and their interest field reads 0 (interest is
  computed on their page), so `past_due_interest` is only meaningful for Jersey City.
  `export` writes `delinquent.csv` (largest first) and `delinquency_summary.csv`.
- WIPP responses are decoded with a GWT object-stream reader using field layouts taken from the
  app's own JavaScript (`SCHEMAS` in `wipp.py`); besides bills, owner and assessments this gives
  open tax-sale liens (certificate, sale date, holder, sale amount, subsequent charges), the
  "in tax sale" flag and the bankruptcy flag. Liens are stored in `liens_json`.
- `analyze_delinquency.py` turns an export into delinquency analytics for one town: owner type
  (`owners.py`: owner-occupied, individual investor, mom-and-pop LLC, corporate, trust/estate,
  public/nonprofit) x property type (condo, single-family, 2-4 family, apartments, commercial, land)
  x severity, with existing liens. Owner names only appear in its `delinquent_properties.csv`.
- `rederive --town T` re-parses stored raw responses with the current parsers (no network), e.g.
  after a parser change; the workflow runs it automatically before fetching.
- If Edmunds redeploys WIPP, calls fail with `//EX`; refresh `PERMUTATION`/`POLICY` in `wipp.py`
  from any request the page makes in a browser.

### Running it on GitHub Actions

`.github/workflows/extract-bills.yml` runs every 6 hours (and on demand from the Actions tab →
*Extract tax bills* → *Run workflow*). Two jobs run in parallel, one per portal host:
`hls` (Jersey City) and `wipp` (Union City, then Hoboken).

- Each job restores its SQLite state from the Actions cache, crawls for up to `max_minutes`
  (default 320), then saves the state back to the cache, so the full first pass (~1 day for
  Jersey City) completes over several runs.
- After the first pass, accounts are re-fetched once they are more than 80 days old
  (`REFRESH_DAYS`), which picks up each new quarterly bill; delinquent accounts are re-checked
  weekly (`RECHECK_DELINQUENT_DAYS`). Bills before tax year 2019 are not kept.
- Every run uploads an `export-hls` / `export-wipp` artifact (accounts.csv, annual.csv, bills.csv.gz),
  kept for 1 day to stay within private-repo artifact storage; the latest run always has one,
  and writes per-town progress to the run summary.
- The state is kept in two places: the Actions cache (fast, but GitHub evicts it after 7 days
  unused) and the **`portal-data` release** (`hls.sqlite.gz`, `wipp.sqlite.gz`, `export-*.tar.gz`),
  replaced after every run and never expiring. If the cache is gone, the next run restores from the
  release. Download the latest database or CSVs any time from the repo's Releases page.
  The release backup only runs while the repository is private.
- **Owner data requires a private repository.** Each job checks the repo's visibility first. If it is
  private (and `include_owners` is on, the default), it runs with `--include-owners --keep-raw`;
  accounts fetched earlier without owners are backfilled. If the repo is public it collects no owner
  fields, exports with `--redact-owners`, and puts a warning in the run summary.

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
