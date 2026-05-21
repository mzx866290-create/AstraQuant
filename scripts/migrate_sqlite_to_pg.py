"""
Migrate data from SQLite (stock_platform.db) to PostgreSQL container.
Run after `docker compose up -d postgres` is healthy.

Usage:
    python scripts/migrate_sqlite_to_pg.py
"""
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2

DB_USER = os.getenv("DB_USER", "stockadmin")
DB_PASS = os.getenv("DB_PASS", "changeme")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "stock_platform")

SQLITE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stock_platform.db")

TABLES_WITH_FK_ORDER = [
    "users",
    "stocks",
    "watchlists",
    "watchlist_items",
    "price_alerts",
    "user_activity_logs",
    "ai_models",
    "ai_usage_logs",
    "user_quotas",
    "research_observations",
    "observation_reviews",
    "weight_suggestion_audits",
    "strategy_weight_patch_proposals",
    "strategy_weight_versions",
    "daily_snapshots",
    "pipeline_run_logs",
    "industry_daily_snapshots",
    "industry_health_scores",
]

BOOLEAN_COLUMNS = {
    "users": ["is_active"],
    "stocks": ["is_active"],
    "price_alerts": ["is_active"],
    "ai_models": ["is_active"],
    "observation_reviews": ["falsification_triggered", "risk_signal_valid"],
    "weight_suggestion_audits": ["accepted"],
}


def get_sqlite_columns(cursor, table):
    cursor.execute(f"PRAGMA table_info([{table}])")
    return [row[1] for row in cursor.fetchall()]


def convert_row(table, columns, row):
    bool_cols = BOOLEAN_COLUMNS.get(table, [])
    if not bool_cols:
        return tuple(row)
    result = []
    for i, col in enumerate(columns):
        val = row[i]
        if col in bool_cols and val is not None:
            val = bool(val)
        result.append(val)
    return tuple(result)


def migrate():
    if not os.path.exists(SQLITE_PATH):
        print(f"SQLite database not found: {SQLITE_PATH}")
        sys.exit(1)

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    pg_conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )
    pg_cur = pg_conn.cursor()

    pg_cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
    """)
    pg_tables = {row[0] for row in pg_cur.fetchall()}

    sqlite_cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    sqlite_tables = {row[0] for row in sqlite_cur.fetchall()}

    print(f"SQLite tables: {len(sqlite_tables)}")
    print(f"PostgreSQL tables: {len(pg_tables)}")
    print()

    # Disable FK and trigger checks
    pg_cur.execute("SET session_replication_role = 'replica';")
    pg_conn.commit()

    # Disable all FK constraints
    pg_cur.execute("""
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN (SELECT conname, conrelid::regclass AS tbl
                      FROM pg_constraint WHERE contype = 'f') LOOP
                EXECUTE 'ALTER TABLE ' || r.tbl || ' DISABLE TRIGGER ALL';
            END LOOP;
        END $$;
    """)
    pg_conn.commit()

    migrated = 0
    for table in TABLES_WITH_FK_ORDER:
        if table not in sqlite_tables:
            print(f"  SKIP {table} (not in SQLite)")
            continue
        if table not in pg_tables:
            print(f"  SKIP {table} (not in PostgreSQL)")
            continue

        columns = get_sqlite_columns(sqlite_cur, table)
        sqlite_cur.execute(f"SELECT * FROM [{table}]")
        rows = sqlite_cur.fetchall()

        if not rows:
            print(f"  SKIP {table} (empty)")
            continue

        pg_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        pg_count = pg_cur.fetchone()[0]
        if pg_count > 0:
            print(f"  SKIP {table} (already has {pg_count} rows in PG)")
            continue

        # Filter columns to only those that exist in PG
        pg_cur.execute(f"""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = '{table}'
        """)
        pg_columns = {row[0] for row in pg_cur.fetchall()}
        col_indices = [i for i, c in enumerate(columns) if c in pg_columns]
        filtered_columns = [columns[i] for i in col_indices]

        col_names = ", ".join(f'"{c}"' for c in filtered_columns)
        placeholders = ", ".join(["%s"] * len(filtered_columns))
        insert_sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'

        batch = []
        for row in rows:
            filtered_row = [row[i] for i in col_indices]
            converted = convert_row(table, filtered_columns, filtered_row)
            batch.append(converted)

        try:
            pg_cur.executemany(insert_sql, batch)
            pg_conn.commit()
            print(f"  OK   {table}: {len(batch)} rows migrated")
            migrated += len(batch)
        except Exception as e:
            pg_conn.rollback()
            pg_cur.execute("SET session_replication_role = 'replica';")
            pg_conn.commit()
            print(f"  ERR  {table}: {e}")

    # Re-enable triggers
    pg_cur.execute("""
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN (SELECT conname, conrelid::regclass AS tbl
                      FROM pg_constraint WHERE contype = 'f') LOOP
                EXECUTE 'ALTER TABLE ' || r.tbl || ' ENABLE TRIGGER ALL';
            END LOOP;
        END $$;
    """)
    pg_cur.execute("SET session_replication_role = 'origin';")
    pg_conn.commit()

    # Reset sequences
    print("\nResetting sequences...")
    pg_cur.execute("""
        SELECT c.relname, a.attname
        FROM pg_class c
        JOIN pg_attribute a ON a.attrelid = c.oid
        JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
        WHERE c.relkind = 'r'
          AND d.adbin::text LIKE '%nextval%'
          AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
    """)
    for table_name, col_name in pg_cur.fetchall():
        try:
            pg_cur.execute(f'SELECT MAX("{col_name}") FROM "{table_name}"')
            max_val = pg_cur.fetchone()[0]
            if max_val:
                seq_name = f"{table_name}_{col_name}_seq"
                pg_cur.execute(f"SELECT setval('{seq_name}', {max_val})")
                pg_conn.commit()
        except Exception:
            pg_conn.rollback()

    pg_conn.close()
    sqlite_conn.close()

    print(f"\nDone! {migrated} total rows migrated.")


if __name__ == "__main__":
    migrate()
