"""Add weight suggestion audit table.

Revision ID: 20260510_0003
Revises: 20260510_0002
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260510_0003"
down_revision = "20260510_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weight_suggestion_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("snapshot_from", sa.DateTime(), nullable=True),
        sa.Column("snapshot_to", sa.DateTime(), nullable=True),
        sa.Column("min_reviews", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("suggestions_json", sa.JSON(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.Column("accepted_by", sa.Integer(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_weight_suggestion_audits_id", "weight_suggestion_audits", ["id"])
    op.create_index("ix_weight_suggestion_audits_generated_at", "weight_suggestion_audits", ["generated_at"])


def downgrade() -> None:
    op.drop_index("ix_weight_suggestion_audits_generated_at", table_name="weight_suggestion_audits")
    op.drop_index("ix_weight_suggestion_audits_id", table_name="weight_suggestion_audits")
    op.drop_table("weight_suggestion_audits")
