#!/usr/bin/env bash
# Copy schema `portal` (accounts, bills, county records, owners) from the current database to Neon,
# check every table's row count, lock the schema away from the website's role, and report Neon's
# size against the Free plan's 1 GB. Schema `site` is not copied (Build site data rebuilds it).
#
#   SOURCE='postgresql://...supabase...:5432/postgres' TARGET='postgresql://...neon.tech/neondb?...' \
#     scripts/copy_to_neon.sh [--replace]
#
# TARGET is Neon's direct connection string (no -pooler). Needs pg_dump/pg_restore/psql 18
# (macOS: brew install libpq && brew link --force libpq). Run by .github/workflows/migrate-to-neon.yml.
# Never overwrites an existing copy unless --replace is given.
set -euo pipefail
: "${SOURCE:?set SOURCE to the current database URL}" "${TARGET:?set TARGET to the Neon direct URL}"
export PGCONNECT_TIMEOUT=20
case "$TARGET" in *-pooler.*) echo "TARGET is Neon's pooled URL; use the direct one (no -pooler in the host)" >&2; exit 1;; esac
case "$SOURCE" in *neon.tech*) echo "SOURCE already points at Neon; nothing to copy" >&2; exit 1;; esac
v=$(pg_dump --version | grep -o '[0-9]\+' | head -1)
[ "$v" -ge 18 ] || { echo "pg_dump $v is too old for Neon's Postgres 18; install version 18" >&2; exit 1; }

echo "== Sizes in the current database"
psql "$SOURCE" -X -v ON_ERROR_STOP=1 -c "
  SELECT c.relname AS table, pg_size_pretty(pg_total_relation_size(c.oid)) AS size, c.reltuples::bigint AS approx_rows
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'portal' AND c.relkind = 'r' ORDER BY pg_total_relation_size(c.oid) DESC"

if [ "$(psql "$TARGET" -XAtc "SELECT count(*) FROM pg_namespace WHERE nspname = 'portal'")" != 0 ]; then
  if [ "${1:-}" = "--replace" ]; then
    psql "$TARGET" -X -v ON_ERROR_STOP=1 -c "DROP SCHEMA portal CASCADE"
  else
    echo "Neon already has a portal schema; re-run with --replace to overwrite it" >&2; exit 1
  fi
fi

echo "== Copying"
dump=$(mktemp -t portal.XXXXXX)
trap 'rm -f "$dump"' EXIT
pg_dump "$SOURCE" --schema=portal --format=custom --no-owner --no-privileges --file="$dump"
pg_restore --dbname="$TARGET" --no-owner --no-privileges --exit-on-error "$dump"

echo "== Locking down and comparing row counts"
psql "$TARGET" -X -v ON_ERROR_STOP=1 -c "REVOKE ALL ON SCHEMA portal FROM PUBLIC" >/dev/null
for role in site_reader anonymous authenticated; do
  psql "$TARGET" -XAtc "SELECT 1 FROM pg_roles WHERE rolname = '$role'" | grep -q 1 || continue
  psql "$TARGET" -X -v ON_ERROR_STOP=1 \
    -c "REVOKE ALL ON SCHEMA portal FROM $role; REVOKE ALL ON ALL TABLES IN SCHEMA portal FROM $role" >/dev/null
done
bad=0
for t in $(psql "$SOURCE" -XAtc "SELECT tablename FROM pg_tables WHERE schemaname = 'portal' ORDER BY 1"); do
  a=$(psql "$SOURCE" -XAtc "SELECT count(*) FROM portal.\"$t\"")
  b=$(psql "$TARGET" -XAtc "SELECT count(*) FROM portal.\"$t\"")
  printf '%-24s before %10s   neon %10s\n' "$t" "$a" "$b"
  [ "$a" = "$b" ] || bad=1
done
[ "$bad" = 0 ] || { echo "Row counts differ (the crawler may have written during the copy); re-run with --replace" >&2; exit 1; }
if psql "$TARGET" -XAtc "SELECT has_schema_privilege('site_reader', 'portal', 'USAGE')" 2>/dev/null | grep -qx t; then
  echo "site_reader can read portal" >&2; exit 1
fi

echo "== Size on Neon"
psql "$TARGET" -X -v ON_ERROR_STOP=1 -c "
  SELECT n.nspname || '.' || c.relname AS table, pg_size_pretty(pg_total_relation_size(c.oid)) AS size
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname IN ('portal', 'site', 'neon_auth') AND c.relkind = 'r'
  ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 15"
mb=$(psql "$TARGET" -XAtc "SELECT pg_database_size(current_database()) / 1048576")
echo "Neon database: ${mb} MB of the Free plan's 1024 MB"
[ "${GITHUB_STEP_SUMMARY:-}" ] && echo "### Neon database: ${mb} MB of the Free plan's 1024 MB" >> "$GITHUB_STEP_SUMMARY"
[ "$mb" -le 850 ] || echo "Warning: over 850 MB; trim before switching (docs/neon.md, Size)"
echo "Copied. Next: point the DATABASE_URL secret at Neon (docs/neon.md)."
