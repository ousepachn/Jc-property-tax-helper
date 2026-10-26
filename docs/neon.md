# Neon: database, owner accounts and file storage

The website runs on one Neon project (org `org-icy-sky-92111300`, project `cool-poetry-73072860`,
branch `production`, region `aws-us-east-2`). `site/neon.ts` declares what the branch provides:

| Service | Used for | Code |
|---|---|---|
| Postgres | schema `site` (public per-property summaries, written by `build_site.py`); later the pipeline's `portal` tables | `site/lib/data.ts` |
| Neon Auth | owner accounts: sign-up, sign-in, sign-out, `/account` | `site/lib/auth/server.ts`, `site/proxy.ts`, `site/app/auth/` |
| Object Storage | owners' documents, bucket `assets` (private), one prefix per user | `site/lib/storage.ts`, `site/app/api/files/` |

The AI Gateway (`aiGateway: true`) is commented out in `neon.ts`: the Free plan doesn't serve it.
Enable it after upgrading, for a future chatbot.

## Local setup

```sh
cd site
neon deploy           # provisions what neon.ts declares and writes the variables into .env.local
npm install && npm run dev
```

`neon deploy` writes `DATABASE_URL`, `DATABASE_URL_UNPOOLED`, `NEON_AUTH_BASE_URL`, `NEON_AUTH_JWKS_URL`
and the `AWS_*` storage variables. Add the two it can't know:

- `NEON_AUTH_COOKIE_SECRET`: `openssl rand -base64 32`
- `SITE_DATABASE_URL`: the read-only `site_reader` role on the **pooled** host (below). The site never
  uses the owner role, so a bug in the site can't read owner names or write anything.

## Read-only role for the website

Run once as the owner (Neon SQL Editor), with a new strong password:

```sql
create role site_reader login password 'CHOOSE-A-STRONG-PASSWORD';
revoke all on schema public from site_reader;
grant usage on schema site to site_reader;
grant select on all tables in schema site to site_reader;
alter default privileges in schema site grant select on tables to site_reader;
```

`SITE_DATABASE_URL` is `DATABASE_URL` with `neondb_owner:<password>` replaced by
`site_reader:<password>`. Quote it in `.env.local`, because it contains `&`.

## Which connection string where

- **Website (Vercel):** `SITE_DATABASE_URL`, the pooled host (`-pooler` in the name). Every page reads
  with single statements over Neon's HTTP endpoint (`@neondatabase/serverless`), so serverless
  functions hold no connections.
- **Pipeline (GitHub Actions `DATABASE_URL` secret):** `DATABASE_URL_UNPOOLED`, the direct host. The
  pipeline sets a session `search_path` and runs long transactions, which the pooler doesn't keep;
  `store.connect` refuses the pooled host.

## Vercel

1. vercel.com → **Add New → Project** → import `ousepachn/jc-property-tax-helper`. If the repository
   isn't listed, **Adjust GitHub App Permissions** and give Vercel access to it.
2. **Root Directory: `site`** (framework Next.js is detected). Leave the build settings as they are.
3. **Environment Variables** → paste the contents of a `.env` file (the box accepts a whole file):
   `SITE_DATABASE_URL`, `NEON_AUTH_BASE_URL`, `NEON_AUTH_COOKIE_SECRET` (a new one for production:
   `openssl rand -base64 32`), `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL_S3`,
   `AWS_REGION`. Values without the surrounding quotes.
4. Deploy. Then Settings → Functions → region **Washington, D.C. (iad1)** or **Cleveland (cle1)**,
   both near Neon's `us-east-2`, and redeploy.
5. Neon Auth only accepts sign-ins from listed domains (localhost is allowed by default).
   `https://jc-property-tax-helper.vercel.app` is listed; add any other domain the site is served
   from, including a preview URL you want to test sign-in on: `neon neon-auth domain add https://...`
   (run in `site/`). An "invalid domain" error means one is missing.

Production deploys the repository's default branch. The Neon-wired site has to be merged there
first; until then use the preview deployment of the working branch.

Neon Auth sends verification and reset emails through Neon's shared sender, which is meant for
development. Set up your own email provider in the Neon console before inviting owners.

## Moving the pipeline from Supabase to Neon

The scheduled jobs write wherever the GitHub secret `DATABASE_URL` points. To move them without
losing the crawled bills:

1. Neon console → project → **Connect** → branch `production`, turn **Connection pooling off**, copy
   the string (the host has no `-pooler`). Or run `neon connection-string production` (direct by default).
2. GitHub → Settings → Secrets and variables → Actions → **New repository secret**
   `NEON_DATABASE_URL` = that string.
3. Copy the data, either way:
   - Actions → **Copy the database to Neon (one-off)** → Run workflow, or
   - from a laptop, with the Postgres 18 client (`brew install libpq && brew link --force libpq`):
     `SOURCE='<Supabase session pooler URL>' TARGET='<Neon direct URL>' scripts/copy_to_neon.sh`

   `scripts/copy_to_neon.sh` copies schema `portal`, compares every table's row count with Supabase,
   locks the schema away from the website's role, and prints Neon's size. It refuses to overwrite an
   existing copy unless given `--replace` ("replace" in the workflow).
4. When it's green: edit secret `DATABASE_URL` and paste the same Neon string, then delete
   `NEON_DATABASE_URL`. The next crawl, site build and county load write to Neon.
5. Keep the Supabase project for a week as a fallback, then delete it. Raw portal responses still
   go to Supabase Storage (`SUPABASE_URL`, `SUPABASE_SECRET_KEY`) until they move to Neon Object
   Storage (5 GB free).

## Size

The Free plan allows 1 GB of Postgres per project; past it, writes are blocked (nothing is deleted).

| What | Size | Notes |
|---|---|---|
| `site` (Jersey City) | 108 MB | rebuilt daily; deleted rows are reused, so it can sit near 2× (about 220 MB) |
| `neon_auth` | under 1 MB | grows with owner accounts |
| `portal` | under 517 MB | Supabase's figure includes dead space from the slimmed bills table; the copy rewrites it compactly. The copy job prints the real number |
| **Expected total** | **about 650–750 MB** | 250+ MB of headroom; bills grow roughly a few % per year |

If it gets close (the copy job warns over 850 MB), trim in this order:

1. Owner history: keep only the latest year in `parcel_owners` (up to ~60 MB).
2. `site` for Hoboken and Union City, when they're added: about 30 MB each; still fits.
3. Old bills: drop `bills` rows older than the four years the site shows.
4. Or upgrade to Launch: $0.35 per GB-month beyond the free amount, no minimum.
