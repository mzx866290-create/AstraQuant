#!/usr/bin/env sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-backups/postgres}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
BACKUP_S3_URI="${BACKUP_S3_URI:-}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT="${BACKUP_DIR}/stock_platform_postgres_${TIMESTAMP}.dump"

mkdir -p "${BACKUP_DIR}"

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:=5432}"
: "${DB_USER:?DB_USER is required}"
: "${DB_NAME:?DB_NAME is required}"

pg_dump -Fc -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -f "${OUTPUT}"
pg_restore --list "${OUTPUT}" >/dev/null

find "${BACKUP_DIR}" -name 'stock_platform_postgres_*.dump' -type f -mtime +"${BACKUP_RETENTION_DAYS}" -delete

if [ -n "${BACKUP_S3_URI}" ]; then
  aws s3 cp "${OUTPUT}" "${BACKUP_S3_URI%/}/postgres/"
fi

echo "${OUTPUT}"
