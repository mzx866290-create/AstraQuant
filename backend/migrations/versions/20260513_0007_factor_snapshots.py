"""Add factor snapshot normalization support."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260513_0007"
down_revision = "20260510_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_observations",
        sa.Column("factor_snapshot_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_observations", "factor_snapshot_json")
