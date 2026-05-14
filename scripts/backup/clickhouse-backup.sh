#!/usr/bin/env sh
set -eu

BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
BACKUP_S3_URI="${BACKUP_S3_URI:-}"
CLICKHOUSE_HOST="${CLICKHOUSE_HOST:-clickhouse}"
CLICKHOUSE_PORT="${CLICKHOUSE_NATIVE_PORT:-9000}"
CLICKHOUSE_USER="${CLICKHOUSE_USER:-default}"
CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD:-}"
CLICKHOUSE_BACKUP_DESTINATION="${CLICKHOUSE_BACKUP_DESTINATION:-Disk('backups', '{name}.zip')}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TABLES="stock_daily stock_minute stock_weekly stock_monthly money_flow north_bound_flow stock_quotes technical_indicators sector_performance"

for table in ${TABLES}; do
  name="stock_platform_${table}_${TIMESTAMP}"
  destination="$(printf '%s' "${CLICKHOUSE_BACKUP_DESTINATION}" | sed "s/{name}/${name}/g")"
  clickhouse-client \
    --host "${CLICKHOUSE_HOST}" \
    --port "${CLICKHOUSE_PORT}" \
    --user "${CLICKHOUSE_USER}" \
    --password "${CLICKHOUSE_PASSWORD}" \
    --query "BACKUP TABLE ${table} TO ${destination}"
done

if [ -n "${BACKUP_S3_URI}" ]; then
  echo "BACKUP_S3_URI is set; configure ClickHouse backup disk or object storage lifecycle for ${BACKUP_S3_URI}"
fi

echo "ClickHouse backup completed at ${TIMESTAMP}; retention=${BACKUP_RETENTION_DAYS}d"
