"""Baseline current SQLAlchemy ORM metadata.

This revision intentionally performs no DDL. Existing environments may have
been initialized by service startup or infra/postgres/init.sql, while local
development can still use the SQLite fallback. Future PostgreSQL schema
changes should be expressed as explicit Alembic revisions after this baseline.

Current ORM tables:
- ai_models
- ai_usage_logs
- company_announcements
- crawl_status
- financial_reports
- observation_reviews
- price_alerts
- research_observations
- stock_news
- stocks
- user_activity_logs
- user_quotas
- users
- watchlist_items
- watchlists
"""
from __future__ import annotations

revision = "20260507_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
