"""Add strategy weight patch proposal table.

Revision ID: 20260510_0004
Revises: 20260510_0003
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260510_0004"
down_revision = "20260510_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_weight_patch_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("audit_id", sa.Integer(), sa.ForeignKey("weight_suggestion_audits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("strategy_id", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("step", sa.Float(), nullable=False),
        sa.Column("max_delta", sa.Float(), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("delta_json", sa.JSON(), nullable=True),
        sa.Column("items_json", sa.JSON(), nullable=True),
        sa.Column("preview_json", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_strategy_weight_patch_proposals_audit_id", "strategy_weight_patch_proposals", ["audit_id"])
    op.create_index("ix_strategy_weight_patch_proposals_strategy_id", "strategy_weight_patch_proposals", ["strategy_id"])
    op.create_index("ix_strategy_weight_patch_proposals_status", "strategy_weight_patch_proposals", ["status"])
    op.create_index("ix_strategy_weight_patch_proposals_created_at", "strategy_weight_patch_proposals", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_strategy_weight_patch_proposals_created_at", table_name="strategy_weight_patch_proposals")
    op.drop_index("ix_strategy_weight_patch_proposals_status", table_name="strategy_weight_patch_proposals")
    op.drop_index("ix_strategy_weight_patch_proposals_strategy_id", table_name="strategy_weight_patch_proposals")
    op.drop_index("ix_strategy_weight_patch_proposals_audit_id", table_name="strategy_weight_patch_proposals")
    op.drop_table("strategy_weight_patch_proposals")
