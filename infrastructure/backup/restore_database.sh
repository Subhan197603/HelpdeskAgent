#!/usr/bin/env bash
# Restore a custom-format archive into a freshly recreated database.
# Required environment: RESTORE_DATABASE, BACKUP_PATH. Optional: BACKUP_USER.
set -euo pipefail

: "${RESTORE_DATABASE:?RESTORE_DATABASE is required}"
: "${BACKUP_PATH:?BACKUP_PATH is required}"
BACKUP_USER="${BACKUP_USER:-postgres}"

pg_restore --list "${BACKUP_PATH}" > /dev/null

psql --username "${BACKUP_USER}" --dbname postgres -X -v ON_ERROR_STOP=1 -Atqc \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
   WHERE datname = '${RESTORE_DATABASE}' AND pid <> pg_backend_pid()" > /dev/null

dropdb --username "${BACKUP_USER}" --if-exists "${RESTORE_DATABASE}"
createdb --username "${BACKUP_USER}" "${RESTORE_DATABASE}"
pg_restore --username "${BACKUP_USER}" --dbname "${RESTORE_DATABASE}" \
  --exit-on-error "${BACKUP_PATH}"
echo "restore complete: ${RESTORE_DATABASE}"
