# Database Migrations

PostgreSQL schema changes are managed with Alembic from this directory.

`env.py` imports `backend.shared.database.DATABASE_URL` and `backend.shared.models.Base.metadata` so migrations use the same URL selection and ORM metadata as the services. SQLite remains available as a local development fallback; production schema changes should be represented as Alembic revisions.
