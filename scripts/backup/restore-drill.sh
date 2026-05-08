#!/usr/bin/env sh
set -eu

POSTGRES_BACKUP_FILE="${POSTGRES_BACKUP_FILE:-}"
CLICKHOUSE_RESTORE_NAME="${CLICKHOUSE_RESTORE_NAME:-}"
CLICKHOUSE_HOST="${CLICKHOUSE_HOST:-clickhouse}"
CLICKHOUSE_PORT="${CLICKHOUSE_NATIVE_PORT:-9000}"
CLICKHOUSE_USER="${CLICKHOUSE_USER:-default}"
CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD:-}"
CLICKHOUSE_RESTORE_DESTINATION="${CLICKHOUSE_RESTORE_DESTINATION:-Disk('backups', '{name}.zip')}"

if [ -z "${POSTGRES_BACKUP_FILE}" ]; then
  echo "POSTGRES_BACKUP_FILE is required for restore drill" >&2
  exit 1
fi

pg_restore --list "${POSTGRES_BACKUP_FILE}" >/dev/null

if [ -n "${CLICKHOUSE_RESTORE_NAME}" ]; then
  destination="$(printf '%s' "${CLICKHOUSE_RESTORE_DESTINATION}" | sed "s/{name}/${CLICKHOUSE_RESTORE_NAME}/g")"
  clickhouse-client \
    --host "${CLICKHOUSE_HOST}" \
    --port "${CLICKHOUSE_PORT}" \
    --user "${CLICKHOUSE_USER}" \
    --password "${CLICKHOUSE_PASSWORD}" \
    --query "RESTORE TABLE stock_daily AS stock_daily_restore_drill FROM ${destination}"
fi

echo "Restore drill checks completed"
