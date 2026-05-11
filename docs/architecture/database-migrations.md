# Database Migration Strategy

SQLite is a development fallback only. It keeps local startup convenient when PostgreSQL is unavailable, but it is not the production schema authority.

PostgreSQL application schema is managed by Alembic from `backend/migrations`. The first revision is a no-op baseline for the current SQLAlchemy ORM metadata; future PostgreSQL schema changes should be added as explicit Alembic revisions and reviewed before running in shared environments.

Current post-baseline revisions include explicit business tables such as `research_observations` and `observation_reviews` for daily research snapshot persistence and T+N review tracking.

ClickHouse remains managed separately through `infra/clickhouse/init.sql` and ETL-owned table definitions. Alembic revisions must not create or mutate ClickHouse tables.

Lightweight tests should verify migration contracts without requiring live PostgreSQL or ClickHouse. Integration coverage for both stores should be added later with docker compose or testcontainers so schema and ETL behavior can be validated against real engines.
