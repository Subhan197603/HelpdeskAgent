#!/usr/bin/env bash
# Logical PostgreSQL backup producing a verified custom-format archive.
# Required environment: BACKUP_DATABASE, BACKUP_PATH. Optional: BACKUP_USER.
set -euo pipefail

: "${BACKUP_DATABASE:?BACKUP_DATABASE is required}"
: "${BACKUP_PATH:?BACKUP_PATH is required}"
BACKUP_USER="${BACKUP_USER:-postgres}"

pg_dump --username "${BACKUP_USER}" --dbname "${BACKUP_DATABASE}" \
  --format=custom --compress=6 --file "${BACKUP_PATH}"

# Verify the archive is readable before declaring the backup complete.
pg_restore --list "${BACKUP_PATH}" > /dev/null
echo "backup complete: ${BACKUP_PATH}"
