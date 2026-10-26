# Hosting: Supabase database + public repository

> Moving to Neon: see [neon.md](neon.md) for the website's database, owner accounts and file
> storage. The steps below still describe the Supabase setup the pipeline uses today.

The crawler's data lives in a Supabase project. The GitHub repository holds only code, so it can be
public, and public repositories get unlimited free GitHub Actions minutes.

| What | Where | Who can see it |
|---|---|---|
| Code, tests, workflow definitions | GitHub (public) | Anyone |
| Run logs and run summaries | GitHub (public) | Anyone. They hold counts and parcel ids only. |
| Accounts, bills, assessments, delinquency, owner names | Supabase Postgres, schema `portal` | You (database owner) |
| County tax board records: floor area, sales with SR-1A codes, assessments by year (`parcels`, `parcel_assessments`); owner names and mailing addresses by year (`parcel_owners`) | Supabase Postgres, schema `portal` | You (database owner) |
| Raw portal responses (full ledger, payments, liens, servicer) | Supabase Storage, private bucket `portal-raw` | You |
| Connection string and secret key | GitHub Actions secrets, your password manager | You |

The tables live in schema `portal`, which Supabase's REST API does not expose. Row level security is
also enabled on every table, with no policies, so the publishable (anon) key cannot read them.

## 1. Create the Supabase project

1. Create a project at supabase.com (the free plan is enough to start; see *Size* below).
2. **Connection string.** Project → **Connect** → **Session pooler** → copy the URI. It looks like
   `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`.
   Use the session pooler (port 5432). The direct connection is IPv6-only, which GitHub runners can't
   reach, and the transaction pooler (port 6543) is refused by the crawler.
3. **Secret key.** Project Settings → **API Keys** → create a **secret key** (`sb_secret_...`).
   It is used only to write raw responses to Storage. The bucket is created, private, on the first
   run with raw responses enabled.

## 2. Add the GitHub secrets

Repository → Settings → Secrets and variables → Actions → **New repository secret**:

| Name | Value |
|---|---|
| `DATABASE_URL` | the session pooler URI from step 1 |
| `SUPABASE_URL` | `https://<ref>.supabase.co` |
| `SUPABASE_SECRET_KEY` | the `sb_secret_...` key |

Secrets are never shown in logs and are not available to workflows triggered from forks.

## 3. Load the existing data (optional)

The crawl can start from scratch: the portals return each account's full history, and the first
Jersey City pass takes about a day of runs. To keep what is already collected instead, copy the
current database from the `portal-data` release **before step 4 deletes it**. Do this on your own
computer, so the data never passes through a public place:

```
gh release download portal-data -p 'hls.sqlite.gz' -p 'wipp.sqlite.gz' -D data/portal
gunzip data/portal/*.sqlite.gz
export DATABASE_URL='postgresql://...'  SUPABASE_URL='https://<ref>.supabase.co'  SUPABASE_SECRET_KEY='sb_secret_...'
python pipeline/extract_bills.py import-sqlite --from data/portal/hls.sqlite
python pipeline/extract_bills.py import-sqlite --from data/portal/wipp.sqlite
python pipeline/extract_bills.py status
```

Running the import again is safe. `--skip-raw` leaves the raw responses behind.

## 4. Remove private data from GitHub, then make the repository public

Do these **in order**. A release, cache or log that exists when the repository goes public becomes
public with it.

1. **Delete the `portal-data` release** (Releases → portal-data → Delete). It holds the full crawler
   databases, with owner names.
2. **Delete the Actions caches** (Actions → Caches → delete every `portal-*` entry).
3. **Delete old workflow runs** of *Extract tax bills*. Their artifacts have expired, but their logs
   and summaries would become public. Deleting the runs is the simple way to be sure.
4. **Decide on git history.** No owner names were ever committed. Older commits of
   `tests/fixtures/hls_jc_313_new_york.json` contain that property's payment methods (card / ACH) and
   the 2025 lien holder's name. The current version has these removed. To remove them from history too,
   either rewrite history (e.g. `git filter-repo`) and force-push every branch, or publish a fresh
   repository from the current code with a single initial commit.
5. Settings → General → Danger zone → **Change visibility → Public**.
6. Actions → *Extract tax bills* → **Run workflow** once to check it. The run summary should show
   per-town counts.

## 5. Publish the website (Vercel)

The site (`site/`, Next.js) reads one table of public per-property summaries, `site.properties`, which
the *Build site data* workflow rebuilds daily. It connects as a read-only database user that can see
only the `site` schema, never `portal`.

1. **Build the data once.** Actions → *Build site data* → Run workflow (or locally:
   `python pipeline/fetch_njogis_parcels.py --county HUDSON --out data/raw/njogis` then
   `python pipeline/build_site.py --parcels data/raw/njogis/parcels_hudson.csv`). This creates the `site` schema.
2. **Create the read-only user.** In Supabase → SQL Editor, with a new strong password:

   ```sql
   create role site_reader login password 'CHOOSE-A-STRONG-PASSWORD';
   grant usage on schema site to site_reader;
   grant select on all tables in schema site to site_reader;
   alter default privileges in schema site grant select on tables to site_reader;
   ```

   It has no access to `portal` (owners, bills, liens). Check with `select has_schema_privilege('site_reader', 'portal', 'usage');`, which should be `false`.
3. **Create the Vercel project.** vercel.com → Add New → Project → import this repository →
   **Root Directory: `site`** (framework: Next.js, detected).
4. **Add one environment variable** (Settings → Environment Variables), `SITE_DATABASE_URL`:

   ```
   postgresql://site_reader.vcdgjfleuxjiemrpfrae:<password>@aws-0-us-east-1.pooler.supabase.com:6543/postgres
   ```

   Note the user name `site_reader.<project ref>` and port **6543** (the transaction pooler suits
   Vercel's short-lived functions; the site only reads). Set the function region to Washington, D.C.
   (`iad1`), next to the database.
5. Deploy. The map loads every parcel once and is cached for a day; property pages refresh hourly.

Local development without the database: `python pipeline/build_site.py --parcels ... --db <sqlite or
$DATABASE_URL> --json-out site/data`, then `cd site && npm install && npm run dev`.

## Day to day

- *Build site data* runs daily and rebuilds the website's per-property summaries.
- *County tax records* runs on the 3rd of each month (and on demand) and reloads the county tax
  board's records for Jersey City, Hoboken and Union City: two requests per town. To load them
  yourself: `python pipeline/fetch_county_records.py --town jersey-city` (uses `$DATABASE_URL`).

- The crawl runs every 6 hours. GitHub turns off scheduled workflows in a public repository after 60
  days without commits; re-enable it from the Actions tab if that happens.
- Supabase pauses free projects after 7 days without activity. The crawl keeps it active.
- Read the data with any Postgres client (the Supabase SQL editor works). Set `search_path` to
  `portal`, or prefix table names: `portal.accounts`, `portal.bills`.
- Build the web page from the database:

  ```
  python pipeline/extract_bills.py export --out data/portal/export/hls --redact-owners   # uses $DATABASE_URL
  python pipeline/build_web_data.py --export data/portal/export/hls --out web/data
  ```

## Size

Measured on the Jersey City crawl (71,192 accounts, 2.36 million bills from 2019 on), loaded into
Postgres with the current table layout:

| | Size | Free plan limit |
|---|---|---|
| Jersey City tables | 284 MB | |
| Hoboken + Union City tables (estimate, about 1/8 of Jersey City) | ~40 MB | |
| **Database total** | **~325 MB** | 500 MB |
| Raw responses, Jersey City (compressed) | 426 MB | |
| Raw responses, Hoboken + Union City | ~20 MB | |
| **Storage total** | **~450 MB** | 1 GB |

Each further tax year adds about 30 MB to the database. Check Project → Settings → Usage once a year.
If the database nears the limit, either raise `MIN_YEAR` in the workflow to keep fewer years of bills,
or move to the Pro plan ($25/month, 8 GB).

Importing the existing Jersey City database (step 3) takes about 1.5 minutes for the tables. Copying
the 71,000 raw responses takes longer, since they upload one at a time: allow 1–2 hours, or use
`--skip-raw` and let the crawl re-collect them over its normal 80-day refresh cycle.
