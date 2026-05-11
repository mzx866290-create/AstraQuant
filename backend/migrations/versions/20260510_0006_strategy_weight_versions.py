"""Add strategy weight version history table.

Revision ID: 20260510_0006
Revises: 20260510_0005
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260510_0006"
down_revision = "20260510_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_weight_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy_id", sa.String(length=50), nullable=False),
        sa.Column("proposal_id", sa.Integer(), sa.ForeignKey("strategy_weight_patch_proposals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("applied_by", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("rolled_back_by", sa.Integer(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
        sa.Column("rollback_error", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_strategy_weight_versions_strategy_id", "strategy_weight_versions", ["strategy_id"])
    op.create_index("ix_strategy_weight_versions_proposal_id", "strategy_weight_versions", ["proposal_id"])
    op.create_index("ix_strategy_weight_versions_version", "strategy_weight_versions", ["version"])
    op.create_index("ix_strategy_weight_versions_created_at", "strategy_weight_versions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_strategy_weight_versions_created_at", table_name="strategy_weight_versions")
    op.drop_index("ix_strategy_weight_versions_version", table_name="strategy_weight_versions")
    op.drop_index("ix_strategy_weight_versions_proposal_id", table_name="strategy_weight_versions")
    op.drop_index("ix_strategy_weight_versions_strategy_id", table_name="strategy_weight_versions")
    op.drop_table("strategy_weight_versions")
