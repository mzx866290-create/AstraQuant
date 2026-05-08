from __future__ import annotations

import configparser
import re
import unittest
from pathlib import Path


class MigrationContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_alembic_config_points_to_backend_migrations(self) -> None:
        config = configparser.ConfigParser()
        config.read(self.ROOT / "alembic.ini", encoding="utf-8")

        self.assertEqual(config["alembic"]["script_location"], "backend/migrations")
        self.assertTrue((self.ROOT / "backend/migrations/env.py").exists())
        self.assertTrue((self.ROOT / "backend/migrations/script.py.mako").exists())
        self.assertTrue((self.ROOT / "backend/migrations/versions").is_dir())

    def test_env_uses_shared_database_url_and_metadata(self) -> None:
        env = (self.ROOT / "backend/migrations/env.py").read_text(encoding="utf-8")

        self.assertIn("from backend.shared.database import DATABASE_URL", env)
        self.assertIn("from backend.shared.models import Base", env)
        self.assertIn("target_metadata = Base.metadata", env)
        self.assertIn("section[\"sqlalchemy.url\"] = get_url()", env)
        self.assertIn("pool.NullPool", env)
        self.assertNotIn("create_all", env)

    def test_baseline_revision_is_noop_and_documents_current_metadata(self) -> None:
        baseline = (self.ROOT / "backend/migrations/versions/20260507_0001_baseline.py").read_text(encoding="utf-8")

        self.assertIn('revision = "20260507_0001"', baseline)
        self.assertIn("down_revision = None", baseline)
        self.assertRegex(baseline, r"def upgrade\(\) -> None:\n    pass")
        self.assertRegex(baseline, r"def downgrade\(\) -> None:\n    pass")

        for table in ("stocks", "users", "watchlists", "ai_models", "crawl_status"):
            self.assertIn(f"- {table}", baseline)

    def test_service_requirements_include_alembic(self) -> None:
        requirement_files = (
            "backend/services/analysis_service/requirements.txt",
            "backend/services/data_crawler/requirements.txt",
            "backend/services/market_service/requirements.txt",
            "backend/services/user_service/requirements.txt",
        )

        for requirement_file in requirement_files:
            with self.subTest(requirement_file=requirement_file):
                requirements = (self.ROOT / requirement_file).read_text(encoding="utf-8")
                self.assertRegex(requirements, re.compile(r"^alembic(?:==|>=)1\.13\.1$", re.M))

    def test_database_migration_docs_define_pg_and_clickhouse_boundaries(self) -> None:
        docs = (self.ROOT / "docs/architecture/database-migrations.md").read_text(encoding="utf-8")

        self.assertIn("SQLite", docs)
        self.assertIn("development fallback", docs)
        self.assertIn("PostgreSQL", docs)
        self.assertIn("Alembic", docs)
        self.assertIn("ClickHouse", docs)
        self.assertIn("init.sql", docs)
        self.assertIn("ETL", docs)
        self.assertIn("docker compose", docs)
        self.assertIn("testcontainers", docs)


if __name__ == "__main__":
    unittest.main()
