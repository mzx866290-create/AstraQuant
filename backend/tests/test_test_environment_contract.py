from __future__ import annotations

import re
import unittest
from pathlib import Path


class TestEnvironmentContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def test_test_compose_defines_pg_clickhouse_and_redis(self) -> None:
        compose = (self.ROOT / "docker-compose.test.yml").read_text(encoding="utf-8")

        for service in ("postgres-test", "clickhouse-test", "redis-test"):
            self.assertIn(f"  {service}:", compose)
            self.assertIn("healthcheck:", compose)

        self.assertIn("postgres:16-alpine", compose)
        self.assertIn("clickhouse/clickhouse-server:24.3", compose)
        self.assertIn("redis:7-alpine", compose)

    def test_test_compose_uses_ephemeral_storage_and_init_schemas(self) -> None:
        compose = (self.ROOT / "docker-compose.test.yml").read_text(encoding="utf-8")

        self.assertIn("tmpfs:", compose)
        self.assertIn("./infra/postgres/init.sql:/docker-entrypoint-initdb.d/00-init.sql:ro", compose)
        self.assertIn("./infra/clickhouse/init.sql:/docker-entrypoint-initdb.d/00-init.sql:ro", compose)
        self.assertNotIn("postgres_data", compose)
        self.assertNotIn("clickhouse_data", compose)

    def test_test_compose_uses_non_default_host_ports(self) -> None:
        compose = (self.ROOT / "docker-compose.test.yml").read_text(encoding="utf-8")

        for host_port in ("15432", "18123", "19000", "16379"):
            self.assertRegex(compose, re.compile(rf"\$\{{[A-Z_]+:-{host_port}\}}"))

        self.assertNotIn('"5432:5432"', compose)
        self.assertNotIn('"8123:8123"', compose)
        self.assertNotIn('"9000:9000"', compose)
        self.assertNotIn('"6379:6379"', compose)

    def test_test_environment_docs_define_boundaries(self) -> None:
        docs = (self.ROOT / "docs/architecture/test-environment.md").read_text(encoding="utf-8")

        for phrase in (
            "docker-compose.test.yml",
            "PostgreSQL",
            "ClickHouse",
            "Redis",
            "SQLite remains a local development fallback only",
            "Alembic revisions",
            "infra/clickhouse/init.sql",
            "static contract tests",
        ):
            self.assertIn(phrase, docs)

    def test_ci_runs_db_integration_smoke_with_required_docker(self) -> None:
        workflow = (self.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("db-integration:", workflow)
        self.assertIn("python scripts/verify_db_integration.py --require-docker", workflow)

    def test_ci_generates_deployment_drill_record_artifact(self) -> None:
        workflow = (self.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        job_match = re.search(
            r"(?ms)^  ci-drill-record:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
            workflow,
        )

        self.assertIsNotNone(job_match)
        job_body = job_match.group("body") if job_match else ""

        self.assertRegex(
            job_body,
            re.compile(
                r"needs:\s*(?:"
                r"\[\s*(?:db-integration\s*,\s*verify|verify\s*,\s*db-integration)\s*\]"
                r"|\n\s+-\s*db-integration\n\s+-\s*verify"
                r"|\n\s+-\s*verify\n\s+-\s*db-integration"
                r")"
            ),
        )
        self.assertRegex(job_body, re.compile(r"(?m)^\s+if:\s*always\(\)\s*$"))
        self.assertIn(
            "python scripts/ops/render_ci_deployment_drill_record.py --output artifacts/ci-deployment-drill-record.md",
            job_body,
        )
        self.assertIn("actions/upload-artifact@v4", job_body)
        self.assertIn("name: ci-deployment-drill-record", job_body)
        self.assertIn("path: artifacts/ci-deployment-drill-record.md", job_body)
        self.assertIn("needs.db-integration.result", job_body)
        self.assertIn("needs.verify.result", job_body)

        for env_var in (
            "DRILL_OWNER",
            "DRILL_REPOSITORY",
            "DRILL_COMMIT_SHA",
            "DRILL_APP_VERSION",
            "DRILL_ENVIRONMENT",
            "DRILL_CI_RUN_URL",
            "DRILL_DB_INTEGRATION_RESULT",
            "DRILL_DEPLOYMENT_SMOKE",
            "DRILL_ROLLBACK_CHECK",
            "DRILL_BLOCKING_ISSUES",
        ):
            self.assertIn(f"{env_var}:", job_body)

    def test_db_integration_script_uses_test_compose_and_required_docker(self) -> None:
        script = (self.ROOT / "scripts/verify_db_integration.py").read_text(encoding="utf-8")

        self.assertIn("docker-compose.test.yml", script)
        self.assertIn("--require-docker", script)
        self.assertIn("docker compose", script)
        for command in ("SELECT 1", "PING"):
            self.assertIn(command, script)


if __name__ == "__main__":
    unittest.main()
