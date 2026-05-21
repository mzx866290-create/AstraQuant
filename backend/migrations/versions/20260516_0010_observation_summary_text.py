"""Add summary_text to research_observations."""

from alembic import op
import sqlalchemy as sa

revision = "20260516_0010"
down_revision = "20260515_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("research_observations") as batch_op:
        batch_op.add_column(sa.Column("summary_text", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("research_observations") as batch_op:
        batch_op.drop_column("summary_text")
