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

Project root `site`. Environment variables: `SITE_DATABASE_URL`, `NEON_AUTH_BASE_URL`,
`NEON_AUTH_COOKIE_SECRET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL_S3`,
`AWS_REGION`. Function region Washington, D.C. (`iad1`) is closest to `us-east-2`; Columbus
(`cle1`) is closer still.

Neon Auth sends verification and reset emails through Neon's shared sender, which is meant for
development. Set up your own email provider in the Neon console before inviting owners.
