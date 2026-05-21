"""Synchronize all public id sequences."""

from alembic import op

revision = "20260517_0012"
down_revision = "20260517_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            rec record;
        BEGIN
            FOR rec IN
                SELECT
                    table_schema,
                    table_name,
                    column_name,
                    pg_get_serial_sequence(format('%I.%I', table_schema, table_name), column_name) AS sequence_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND column_name = 'id'
            LOOP
                IF rec.sequence_name IS NOT NULL THEN
                    EXECUTE format(
                        'SELECT setval(%L, COALESCE((SELECT MAX(%I) FROM %I.%I), 0) + 1, false)',
                        rec.sequence_name,
                        rec.column_name,
                        rec.table_schema,
                        rec.table_name
                    );
                END IF;
            END LOOP;
        END
        $$;
        """
    )


def downgrade() -> None:
    pass
