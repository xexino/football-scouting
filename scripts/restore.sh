#!/usr/bin/env bash
# Restore a backup produced by backup.sh. DESTRUCTIVE: replaces existing objects.
# Usage: DATABASE_URL=postgresql://raja:pw@host:5432/raja_scout scripts/restore.sh backups/raja_scout_X.dump
set -euo pipefail
FILE="${1:?backup file required}"
URL="${DATABASE_URL:?set DATABASE_URL}"
URL="${URL/postgresql+psycopg:/postgresql:}"
read -r -p "This will overwrite data in the target database. Type RESTORE to continue: " ok
[ "$ok" = "RESTORE" ] || { echo "Aborted"; exit 1; }
pg_restore --clean --if-exists --no-owner --dbname="$URL" "$FILE"
echo "Restore complete."
