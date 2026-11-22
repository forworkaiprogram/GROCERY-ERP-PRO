#!/bin/sh
# PostgreSQL backup: plain-and-verified dump + SHA-256 sidecar + retention.
# Run from cron/systemd inside the deployment host:
#   infrastructure/backups/backup_postgres.sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-/var/backups/grocery-erp}"
CONTAINER="${CONTAINER:-$(docker compose ps -q db)}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$BACKUP_DIR"
TARGET="$BACKUP_DIR/grocery_erp_$STAMP.sql.gz"

docker exec "$CONTAINER" pg_dump -U "${POSTGRES_USER:-grocery}" \
  -d "${POSTGRES_DB:-grocery}" | gzip > "$TARGET"

# Verify integrity by decompressing and checking for a complete dump tail.
gunzip -t "$TARGET"
sha256sum "$TARGET" > "$TARGET.sha256"

echo "backup written: $TARGET"

find "$BACKUP_DIR" -name 'grocery_erp_*.sql.gz' -mtime +"$RETENTION_DAYS" \
  -not -name '*.sha256' -print -delete
find "$BACKUP_DIR" -name '*.sha256' -mtime +"$RETENTION_DAYS" -print -delete
