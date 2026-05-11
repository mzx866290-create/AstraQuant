"""Add strategy weight patch apply audit fields.

Revision ID: 20260510_0005
Revises: 20260510_0004
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260510_0005"
down_revision = "20260510_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("strategy_weight_patch_proposals", sa.Column("applied_by", sa.Integer(), nullable=True))
    op.add_column("strategy_weight_patch_proposals", sa.Column("applied_at", sa.DateTime(), nullable=True))
    op.add_column("strategy_weight_patch_proposals", sa.Column("applied_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("strategy_weight_patch_proposals", "applied_error")
    op.drop_column("strategy_weight_patch_proposals", "applied_at")
    op.drop_column("strategy_weight_patch_proposals", "applied_by")
