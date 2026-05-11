"""Add research observation and review tables.

Revision ID: 20260510_0002
Revises: 20260507_0001
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260510_0002"
down_revision = "20260507_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_date", sa.DateTime(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("strategy_id", sa.String(length=50), nullable=False),
        sa.Column("regime", sa.String(length=30), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("score_breakdown_json", sa.JSON(), nullable=True),
        sa.Column("evidence_chain_json", sa.JSON(), nullable=True),
        sa.Column("debate_json", sa.JSON(), nullable=True),
        sa.Column("veto_result_json", sa.JSON(), nullable=True),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("snapshot_date", "symbol", "strategy_id", name="uix_research_observation"),
    )
    op.create_index("ix_research_observations_id", "research_observations", ["id"])
    op.create_index("ix_research_observations_snapshot_date", "research_observations", ["snapshot_date"])
    op.create_index("ix_research_observations_symbol", "research_observations", ["symbol"])
    op.create_index("ix_research_observations_strategy_id", "research_observations", ["strategy_id"])
    op.create_index("ix_research_observations_regime", "research_observations", ["regime"])
    op.create_index("ix_research_observations_created_at", "research_observations", ["created_at"])

    op.create_table(
        "observation_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observation_id", sa.Integer(), sa.ForeignKey("research_observations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_offset", sa.String(length=10), nullable=False),
        sa.Column("review_date", sa.DateTime(), nullable=False),
        sa.Column("close_price", sa.Float(), nullable=True),
        sa.Column("return_pct", sa.Float(), nullable=True),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=True),
        sa.Column("falsification_triggered", sa.Boolean(), nullable=True),
        sa.Column("risk_signal_valid", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("observation_id", "review_offset", name="uix_observation_review"),
    )
    op.create_index("ix_observation_reviews_id", "observation_reviews", ["id"])
    op.create_index("ix_observation_reviews_observation_id", "observation_reviews", ["observation_id"])
    op.create_index("ix_observation_reviews_review_offset", "observation_reviews", ["review_offset"])
    op.create_index("ix_observation_reviews_review_date", "observation_reviews", ["review_date"])
    op.create_index("ix_observation_reviews_created_at", "observation_reviews", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_observation_reviews_created_at", table_name="observation_reviews")
    op.drop_index("ix_observation_reviews_review_date", table_name="observation_reviews")
    op.drop_index("ix_observation_reviews_review_offset", table_name="observation_reviews")
    op.drop_index("ix_observation_reviews_observation_id", table_name="observation_reviews")
    op.drop_index("ix_observation_reviews_id", table_name="observation_reviews")
    op.drop_table("observation_reviews")

    op.drop_index("ix_research_observations_created_at", table_name="research_observations")
    op.drop_index("ix_research_observations_regime", table_name="research_observations")
    op.drop_index("ix_research_observations_strategy_id", table_name="research_observations")
    op.drop_index("ix_research_observations_symbol", table_name="research_observations")
    op.drop_index("ix_research_observations_snapshot_date", table_name="research_observations")
    op.drop_index("ix_research_observations_id", table_name="research_observations")
    op.drop_table("research_observations")
