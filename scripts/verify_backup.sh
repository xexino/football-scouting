#!/usr/bin/env bash
# Verify a backup: restore it into a temporary database, then compare every table's row
# count with the manifest written by backup.sh (or with the live database if no manifest),
# and check the Alembic schema revision. The temporary database is always dropped.
# Usage: DATABASE_URL=postgresql://user:pw@host:5432/raja_scout scripts/verify_backup.sh FILE.dump
# The database user needs CREATEDB (or set VERIFY_ADMIN_URL to a connection that has it).
set -euo pipefail
FILE="${1:?backup file required}"
URL="${DATABASE_URL:?set DATABASE_URL}"; URL="${URL/postgresql+psycopg:/postgresql:}"
ADMIN_URL="${VERIFY_ADMIN_URL:-$URL}"; ADMIN_URL="${ADMIN_URL/postgresql+psycopg:/postgresql:}"
TMPDB="raja_verify_$(date +%s)_$$"
BASE="${URL%%\?*}"; TMPURL="${BASE%/*}/${TMPDB}"
psql "$ADMIN_URL" -qc "CREATE DATABASE ${TMPDB}"
trap 'psql "$ADMIN_URL" -qc "DROP DATABASE IF EXISTS ${TMPDB}" >/dev/null 2>&1 || true' EXIT
pg_restore --no-owner --exit-on-error --dbname="$TMPURL" "$FILE"

counts() {  # $1 = connection url -> "table count" lines
  psql "$1" -Atq -c "SELECT format('SELECT %L, count(*) FROM %I.%I', table_name, table_schema, table_name)
                     FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'
                     ORDER BY table_name" | while read -r q; do psql "$1" -Atq -F' ' -c "$q"; done
}
if [ -f "$FILE.counts" ]; then EXPECTED="$(cat "$FILE.counts")"; SRC="manifest"; else EXPECTED="$(counts "$URL")"; SRC="live database"; fi
RESTORED="$(counts "$TMPURL")"
FAIL=0
printf "%-26s %10s %10s\n" "table" "expected" "restored"
while read -r t n; do
  r="$(echo "$RESTORED" | awk -v t="$t" '$1==t{print $2}')"
  flag=""; [ "$r" = "$n" ] || { flag="  <-- MISMATCH"; FAIL=1; }
  printf "%-26s %10s %10s%s\n" "$t" "$n" "${r:-missing}" "$flag"
done <<< "$EXPECTED"
REV="$(psql "$TMPURL" -Atq -c 'SELECT version_num FROM alembic_version' 2>/dev/null || echo none)"
echo "Schema revision in backup: ${REV}"
[ "$REV" != "none" ] || { echo "No alembic_version table in backup"; FAIL=1; }
if [ "$FAIL" = 0 ]; then echo "BACKUP VERIFIED (compared with $SRC)"; else echo "BACKUP VERIFICATION FAILED"; exit 1; fi
