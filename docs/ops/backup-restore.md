# Backup And Restore Runbook

## Backup Schedule

- PostgreSQL: daily `pg_dump -Fc`, retained for `BACKUP_RETENTION_DAYS`.
- ClickHouse: daily `BACKUP TABLE ... TO Disk(...)`, retained by the ClickHouse backup destination and optional object storage lifecycle.
- Restore drill: run at least quarterly against a disposable environment.

## Commands

```bash
scripts/backup/postgres-backup.sh
scripts/backup/clickhouse-backup.sh
scripts/backup/restore-drill.sh
```

## Object Storage

Set `BACKUP_S3_URI` to upload backup artifacts with `aws s3 cp`. If it is empty, scripts keep artifacts in `BACKUP_DIR`.

## Restore Drill

The restore drill validates that a PostgreSQL custom-format dump can be read by `pg_restore --list` and that ClickHouse restore commands are present. A full production restore must use an isolated environment first.
