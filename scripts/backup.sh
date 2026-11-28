#!/usr/bin/env bash
# Full PostgreSQL backup (custom format, compressed) + row-count manifest, with retention.
# Usage: DATABASE_URL=postgresql://raja:pw@host:5432/raja_scout scripts/backup.sh [backup_dir]
# Verify every backup with scripts/verify_backup.sh (restores it into a scratch database).
set -euo pipefail
DIR="${1:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
URL="${DATABASE_URL:?set DATABASE_URL}"
URL="${URL/postgresql+psycopg:/postgresql:}"   # strip SQLAlchemy driver suffix
mkdir -p "$DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
FILE="$DIR/raja_scout_${STAMP}.dump"
pg_dump --format=custom --no-owner --dbname="$URL" --file="$FILE"
# Manifest of row counts (taken right after the dump; heavy concurrent writes can make it differ slightly).
psql "$URL" -Atq -c "SELECT format('SELECT %L, count(*) FROM %I.%I', table_name, table_schema, table_name)
                     FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'
                     ORDER BY table_name" | while read -r q; do psql "$URL" -Atq -F' ' -c "$q"; done > "$FILE.counts"
echo "Backup written: $FILE (+ manifest $FILE.counts)"
find "$DIR" -name 'raja_scout_*.dump*' -mtime +"$KEEP_DAYS" -print -delete
