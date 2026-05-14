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

        for table in ("stocks", "users", "watchlists", "ai_models", "crawl_status", "research_observations", "observation_reviews"):
            self.assertIn(f"- {table}", baseline)

    def test_research_observation_revision_exists_and_targets_baseline(self) -> None:
        revision = (self.ROOT / "backend/migrations/versions/20260510_0002_research_observations.py").read_text(encoding="utf-8")

        self.assertIn('revision = "20260510_0002"', revision)
        self.assertIn('down_revision = "20260507_0001"', revision)
        self.assertIn('op.create_table(\n        "research_observations"', revision)
        self.assertIn('op.create_table(\n        "observation_reviews"', revision)

    def test_weight_suggestion_audit_revision_exists_and_targets_research_revision(self) -> None:
        revision = (self.ROOT / "backend/migrations/versions/20260510_0003_weight_suggestion_audits.py").read_text(encoding="utf-8")

        self.assertIn('revision = "20260510_0003"', revision)
        self.assertIn('down_revision = "20260510_0002"', revision)
        self.assertIn('op.create_table(\n        "weight_suggestion_audits"', revision)
        self.assertIn('"suggestions_json"', revision)
        self.assertIn('"summary_json"', revision)

    def test_strategy_weight_patch_proposal_revision_exists_and_targets_audit_revision(self) -> None:
        revision = (self.ROOT / "backend/migrations/versions/20260510_0004_strategy_weight_patch_proposals.py").read_text(encoding="utf-8")

        self.assertIn('revision = "20260510_0004"', revision)
        self.assertIn('down_revision = "20260510_0003"', revision)
        self.assertIn('op.create_table(\n        "strategy_weight_patch_proposals"', revision)
        self.assertIn('"preview_json"', revision)

    def test_strategy_weight_patch_apply_revision_exists_and_targets_proposal_revision(self) -> None:
        revision = (self.ROOT / "backend/migrations/versions/20260510_0005_strategy_weight_patch_apply.py").read_text(encoding="utf-8")

        self.assertIn('revision = "20260510_0005"', revision)
        self.assertIn('down_revision = "20260510_0004"', revision)
        self.assertIn('"applied_at"', revision)
        self.assertIn('"applied_error"', revision)

    def test_strategy_weight_versions_revision_exists_and_targets_apply_revision(self) -> None:
        revision = (self.ROOT / "backend/migrations/versions/20260510_0006_strategy_weight_versions.py").read_text(encoding="utf-8")

        self.assertIn('revision = "20260510_0006"', revision)
        self.assertIn('down_revision = "20260510_0005"', revision)
        self.assertIn('op.create_table(\n        "strategy_weight_versions"', revision)
        self.assertIn('"rollback_error"', revision)

    def test_factor_snapshot_revision_exists_and_targets_strategy_weight_versions_revision(self) -> None:
        revision = (self.ROOT / "backend/migrations/versions/20260513_0007_factor_snapshots.py").read_text(encoding="utf-8")

        self.assertIn('revision = "20260513_0007"', revision)
        self.assertIn('down_revision = "20260510_0006"', revision)
        self.assertIn('factor_snapshot_json', revision)
        self.assertIn('op.add_column', revision)

    def test_postgres_init_sql_bootstraps_research_tables(self) -> None:
        init_sql = (self.ROOT / "infra/postgres/init.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS research_observations", init_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS observation_reviews", init_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS weight_suggestion_audits", init_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS strategy_weight_patch_proposals", init_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS strategy_weight_versions", init_sql)
        self.assertIn("factor_snapshot_json", init_sql)
        self.assertIn("applied_error TEXT", init_sql)
        self.assertIn("rollback_error  TEXT", init_sql)

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
