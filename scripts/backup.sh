#!/usr/bin/env bash
# Full PostgreSQL backup (custom format, compressed) with simple retention.
# Usage: DATABASE_URL=postgresql://raja:pw@host:5432/raja_scout scripts/backup.sh [backup_dir]
set -euo pipefail
DIR="${1:-./backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
URL="${DATABASE_URL:?set DATABASE_URL}"
URL="${URL/postgresql+psycopg:/postgresql:}"   # strip SQLAlchemy driver suffix
mkdir -p "$DIR"
FILE="$DIR/raja_scout_$(date +%Y%m%d_%H%M%S).dump"
pg_dump --format=custom --no-owner --dbname="$URL" --file="$FILE"
echo "Backup written: $FILE"
find "$DIR" -name 'raja_scout_*.dump' -mtime +"$KEEP_DAYS" -print -delete
