"""Add industry daily snapshot and health score tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260514_0008"
down_revision = "20260513_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "industry_daily_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("industry_code", sa.String(20), nullable=False, index=True),
        sa.Column("industry_name", sa.String(50), nullable=False),
        sa.Column("trade_date", sa.String(10), nullable=False, index=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("ma5", sa.Float(), nullable=True),
        sa.Column("ma20", sa.Float(), nullable=True),
        sa.Column("ma60", sa.Float(), nullable=True),
        sa.Column("ret_5d", sa.Float(), nullable=True),
        sa.Column("ret_20d", sa.Float(), nullable=True),
        sa.Column("ret_60d", sa.Float(), nullable=True),
        sa.Column("money_flow_1d", sa.Float(), nullable=True),
        sa.Column("money_flow_5d", sa.Float(), nullable=True),
        sa.Column("money_flow_20d", sa.Float(), nullable=True),
        sa.Column("source", sa.String(20), server_default="akshare"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("industry_code", "trade_date", name="uix_industry_daily_snapshot"),
    )

    op.create_table(
        "industry_health_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("industry_code", sa.String(20), nullable=False, index=True),
        sa.Column("industry_name", sa.String(50), nullable=False),
        sa.Column("trade_date", sa.String(10), nullable=False, index=True),
        sa.Column("health_score", sa.Integer(), nullable=True),
        sa.Column("trend_score", sa.Integer(), nullable=True),
        sa.Column("money_score", sa.Integer(), nullable=True),
        sa.Column("momentum_score", sa.Integer(), nullable=True),
        sa.Column("flags", sa.JSON(), nullable=True),
        sa.Column("is_healthy", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("industry_code", "trade_date", name="uix_industry_health_score"),
    )


def downgrade() -> None:
    op.drop_table("industry_health_scores")
    op.drop_table("industry_daily_snapshots")
