"""Synchronize auth-related PostgreSQL sequences."""

from alembic import op

revision = "20260517_0011"
down_revision = "20260516_0010"
branch_labels = None
depends_on = None


def _sync_sequence(table_name: str, column_name: str = "id") -> None:
    op.execute(
        f"""
        DO $$
        DECLARE
            sequence_name text;
        BEGIN
            SELECT pg_get_serial_sequence('{table_name}', '{column_name}') INTO sequence_name;
            IF sequence_name IS NOT NULL THEN
                EXECUTE format(
                    'SELECT setval(%L, COALESCE((SELECT MAX({column_name}) FROM {table_name}), 0) + 1, false)',
                    sequence_name
                );
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _sync_sequence("users")
    _sync_sequence("user_quotas")


def downgrade() -> None:
    pass
