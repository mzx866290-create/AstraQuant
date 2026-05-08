# Test Environment

The canonical integration-test infrastructure is `docker-compose.test.yml`.
It starts only PostgreSQL, ClickHouse, and Redis so backend tests can run
against the same durable stores used in production without booting the whole
application stack.

## Services

- PostgreSQL uses `infra/postgres/init.sql` and an in-memory container volume.
- ClickHouse uses `infra/clickhouse/init.sql` and an in-memory container volume.
- Redis runs without persistence and with an LRU memory policy.

## Defaults

- PostgreSQL: `localhost:15432`, database `stock_platform_test`, user `stocktest`.
- ClickHouse HTTP: `localhost:18123`.
- ClickHouse native: `localhost:19000`.
- Redis: `localhost:16379`.

The ports and credentials are overridable through `TEST_*` environment
variables. Test containers intentionally use `tmpfs` instead of named volumes
so each run starts from a clean schema.

## Boundary

SQLite remains a local development fallback only. PostgreSQL schema changes
should be represented as Alembic revisions, while ClickHouse table shape is
owned by `infra/clickhouse/init.sql` and the ETL write-contract tests.

When Docker is unavailable on a developer workstation, static contract tests
still verify that the test compose file wires the same schemas and health
checks expected by CI.
