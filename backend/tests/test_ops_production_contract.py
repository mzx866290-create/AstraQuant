from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


class OpsProductionContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]

    def _service_block(self, compose: str, service_name: str) -> str:
        match = re.search(rf"^  {re.escape(service_name)}:\n(?P<body>(?:    .*\n|      .*\n|        .*\n|          .*\n|            .*\n)*)", compose, re.M)
        self.assertIsNotNone(match, f"{service_name} service block is missing")
        return match.group("body")

    def test_prod_compose_uses_images_without_public_backend_ports(self) -> None:
        compose = (self.ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

        self.assertNotIn("\n    build:", compose)
        self.assertNotIn(":latest", compose)

        for service in ("market-service", "user-service", "analysis-service", "data-crawler", "web"):
            block = self._service_block(compose, service)
            self.assertIn("image:", block)
            self.assertIn("${APP_VERSION:", block)
            self.assertIn("restart: unless-stopped", block)

        for service in ("postgres", "clickhouse", "redis", "market-service", "user-service", "analysis-service", "data-crawler", "prometheus", "grafana", "alertmanager"):
            block = self._service_block(compose, service)
            self.assertNotIn("\n    ports:", block, f"{service} must not expose host ports in production")

        web_block = self._service_block(compose, "web")
        self.assertIn('"80:80"', web_block)

    def test_prod_compose_wires_alertmanager_and_grafana_provisioning(self) -> None:
        compose = (self.ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

        for service in ("prometheus", "grafana", "alertmanager"):
            self.assertIn(f"  {service}:", compose)
            self.assertIn("restart: unless-stopped", self._service_block(compose, service))

        self.assertIn("./infra/grafana/provisioning:/etc/grafana/provisioning:ro", compose)
        self.assertIn("./infra/grafana/dashboards:/var/lib/grafana/dashboards:ro", compose)
        self.assertIn("./infra/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro", compose)
        self.assertIn("--config.expand-env", compose)
        self.assertIn("ALERT_WEBHOOK_URL: ${ALERT_WEBHOOK_URL:?", compose)
        self.assertIn("--storage.tsdb.retention.time=${PROMETHEUS_RETENTION:-15d}", compose)

    def test_grafana_dashboards_and_datasource_are_provisioned(self) -> None:
        datasource = (self.ROOT / "infra/grafana/provisioning/datasources/prometheus.yml").read_text(encoding="utf-8")
        provider = (self.ROOT / "infra/grafana/provisioning/dashboards/dashboards.yml").read_text(encoding="utf-8")

        self.assertIn("uid: Prometheus", datasource)
        self.assertIn("url: http://prometheus:9090", datasource)
        self.assertIn("/var/lib/grafana/dashboards", provider)

        dashboards = {
            "business-overview.json": ("stock_platform_http_requests_total", "stock_platform_http_request_duration_seconds"),
            "crawler-health.json": ("stock_platform_data_crawler_task_last_status", "stock_platform_data_crawler_scheduler_running"),
            "system-overview.json": ("scrape_samples_scraped", "prometheus_tsdb_head_series"),
        }
        for filename, expected_metrics in dashboards.items():
            raw = (self.ROOT / "infra/grafana/dashboards" / filename).read_text(encoding="utf-8")
            json.loads(raw)
            for metric in expected_metrics:
                self.assertIn(metric, raw)

    def test_prometheus_alertmanager_and_runbook_contract(self) -> None:
        prometheus = (self.ROOT / "infra/prometheus/prometheus.yml").read_text(encoding="utf-8")
        alertmanager = (self.ROOT / "infra/alertmanager/alertmanager.yml").read_text(encoding="utf-8")
        rules = (self.ROOT / "infra/prometheus/rules/service-alerts.yml").read_text(encoding="utf-8")

        self.assertIn("alertmanager:9093", prometheus)
        self.assertIn("webhook_configs", alertmanager)
        self.assertIn("${ALERT_WEBHOOK_URL}", alertmanager)
        self.assertIn("send_resolved: true", alertmanager)

        alert_names = re.findall(r"alert: ([A-Za-z0-9_]+)", rules)
        self.assertGreaterEqual(len(alert_names), 5)
        for alert_name in alert_names:
            block = rules[rules.index(f"alert: {alert_name}") :]
            block = block.split("\n      - alert:", 1)[0]
            self.assertIn("severity:", block)
            self.assertIn("summary:", block)
            self.assertIn("description:", block)
            self.assertIn("runbook_url:", block)

            runbook = (self.ROOT / "docs/ops/monitoring-runbook.md").read_text(encoding="utf-8")
            self.assertIn(alert_name, runbook)

    def test_alert_webhook_drill_script_and_record_template_contract(self) -> None:
        script_path = self.ROOT / "scripts/ops/alert_webhook_drill.py"
        runbook = (self.ROOT / "docs/ops/monitoring-runbook.md").read_text(encoding="utf-8")
        env_template = (self.ROOT / ".env.production.example").read_text(encoding="utf-8")
        workflow = (self.ROOT / ".github/workflows/alert-webhook-drill.yml").read_text(encoding="utf-8")

        self.assertTrue(script_path.exists(), "alert webhook drill script is missing")
        script = script_path.read_text(encoding="utf-8")
        self.assertIn("urllib.request", script)
        self.assertIn("--dry-run", script)
        self.assertIn("--send", script)
        self.assertIn("ALERT_WEBHOOK_URL", script)
        self.assertIn("RECORD_TEMPLATE", script)

        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--url",
                "https://alerts.example.invalid/token",
                "--dry-run",
                "--status",
                "resolved",
            ],
            cwd=self.ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("DRY-RUN: would POST resolved payload", result.stdout)
        self.assertIn('"status": "resolved"', result.stdout)
        self.assertNotIn("token", result.stdout)

        record = subprocess.run(
            [sys.executable, str(script_path), "--record-template"],
            cwd=self.ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        for field in (
            "时间",
            "负责人",
            "接收端",
            "GitHub Actions run URL",
            "`send` mode",
            "`status` input",
            "HTTP firing response",
            "HTTP resolved response",
            "触发告警",
            "收到时间",
            "恢复告警",
            "Artifact `alert-webhook-drill-record`",
            "结论",
        ):
            self.assertIn(field, record)
            self.assertIn(field, runbook)

        self.assertIn("Feishu", runbook)
        self.assertIn("DingTalk", runbook)
        self.assertIn("Slack", runbook)
        self.assertIn("ALERT_WEBHOOK_URL=<real-alert-webhook-url>", env_template)
        self.assertIn("--record-output alert-webhook-drill-record.md", runbook)

        self.assertIn("workflow_dispatch", workflow)
        self.assertIn("secrets.ALERT_WEBHOOK_URL", workflow)
        self.assertIn("python scripts/ops/alert_webhook_drill.py --send", workflow)
        self.assertIn("--record-output artifacts/alert-webhook-drill-record.md", workflow)
        self.assertIn("upload-artifact", workflow)
        self.assertIn("if-no-files-found: error", workflow)
        self.assertIn("alert-webhook-drill-record", runbook)
        self.assertIn("python scripts/ops/validate_alert_webhook_drill_record.py", runbook)
        self.assertIn("python scripts/ops/finalize_ops_drill_archive.py", runbook)
        self.assertIn("manifest.json", runbook)
        self.assertIn("manifest.sha256", runbook)
        self.assertIn(".sealed", runbook)
        self.assertIn(".zip.sha256", runbook)
        self.assertIn("ops-drills/<yyyy-mm-dd>-production-<app-version>/", runbook)

    def test_ops_docs_and_backup_scripts_exist(self) -> None:
        docs = (
            "docs/ops/production-deploy.md",
            "docs/ops/monitoring-runbook.md",
            "docs/ops/backup-restore.md",
            "docs/ops/ci-deployment-drill-record.md",
            "docs/ops/ops-drill-archive-runbook.md",
        )
        for doc in docs:
            self.assertTrue((self.ROOT / doc).exists(), f"{doc} is missing")

        readme = (self.ROOT / "README.md").read_text(encoding="utf-8")
        for doc in docs:
            self.assertIn(doc, readme)

        production_deploy = (self.ROOT / "docs/ops/production-deploy.md").read_text(encoding="utf-8")
        self.assertIn("python scripts/ops/verify_ops_drill_readiness.py --env-file .env.production", production_deploy)

        readiness = (self.ROOT / "scripts/ops/verify_ops_drill_readiness.py").read_text(encoding="utf-8")
        self.assertIn("--env-file", readiness)
        self.assertIn("--summary-json", readiness)

        postgres_backup = (self.ROOT / "scripts/backup/postgres-backup.sh").read_text(encoding="utf-8")
        clickhouse_backup = (self.ROOT / "scripts/backup/clickhouse-backup.sh").read_text(encoding="utf-8")
        restore_drill = (self.ROOT / "scripts/backup/restore-drill.sh").read_text(encoding="utf-8")

        self.assertIn("set -eu", postgres_backup)
        self.assertIn("pg_dump -Fc", postgres_backup)
        self.assertIn("pg_restore --list", postgres_backup)
        self.assertIn("BACKUP_RETENTION_DAYS", postgres_backup)
        self.assertIn("BACKUP_S3_URI", postgres_backup)

        self.assertIn("BACKUP TABLE", clickhouse_backup)
        self.assertIn("CLICKHOUSE_BACKUP_DESTINATION", clickhouse_backup)
        self.assertIn("BACKUP_RETENTION_DAYS", clickhouse_backup)
        self.assertIn("BACKUP_S3_URI", clickhouse_backup)

        self.assertIn("pg_restore --list", restore_drill)
        self.assertIn("RESTORE TABLE", restore_drill)

    def test_ops_drill_archive_runbook_covers_download_prepare_validate_and_storage(self) -> None:
        runbook = (self.ROOT / "docs/ops/ops-drill-archive-runbook.md").read_text(encoding="utf-8")

        for expected in (
            "gh run download <ci-run-id> -n ci-deployment-drill-record",
            "gh run download <alert-run-id> -n alert-webhook-drill-record",
            "python scripts/ops/prepare_ops_drill_archive.py",
            "python scripts/ops/verify_ops_drill_readiness.py",
            "python scripts/ops/finalize_ops_drill_archive.py",
            "python scripts/ops/finalize_ops_drill_archive.py --verify-package",
            "python scripts/ops/validate_ci_deployment_drill_record.py",
            "python scripts/ops/validate_alert_webhook_drill_record.py",
            "python scripts/ops/validate_ops_drill_archive.py completed",
            "raw/",
            "completed/",
            "validation.txt",
            "manifest.json",
            "manifest.sha256",
            ".sealed",
            "<archive>.zip",
            "<archive>.zip.sha256",
            "object-lock/WORM",
            "Do not paste real webhook URLs or tokens",
            "Store the completed package outside the source repository",
        ):
            self.assertIn(expected, runbook)

    def test_ci_deployment_drill_record_captures_real_evidence_fields(self) -> None:
        record = (self.ROOT / "docs/ops/ci-deployment-drill-record.md").read_text(encoding="utf-8")
        workflow = (self.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        alert_workflow = (self.ROOT / ".github/workflows/alert-webhook-drill.yml").read_text(encoding="utf-8")

        for field in (
            "Commit SHA",
            "APP_VERSION",
            "CI workflow run URL",
            "`db-integration` job result",
            "PostgreSQL smoke result",
            "ClickHouse smoke result",
            "Redis smoke result",
            "Backend coverage gate result",
            "Frontend smoke result",
            "Alert Webhook Drill run URL",
            "Artifact `alert-webhook-drill-record`",
            "Pull immutable images",
            "Prometheus readiness",
            "Previous known-good APP_VERSION",
            "Production-ready conclusion",
        ):
            self.assertIn(field, record)

        self.assertIn("python scripts/verify_db_integration.py --require-docker", workflow)
        self.assertIn("python scripts/ops/validate_ci_deployment_drill_record.py", record)
        self.assertIn("python scripts/ops/finalize_ops_drill_archive.py", record)
        self.assertIn("python scripts/ops/finalize_ops_drill_archive.py --verify-package", record)
        self.assertIn("python scripts/ops/verify_ops_drill_readiness.py", record)
        self.assertIn("manifest.json", record)
        self.assertIn("manifest.sha256", record)
        self.assertIn(".sealed", record)
        self.assertIn(".zip.sha256", record)
        self.assertIn("ops-drills/<yyyy-mm-dd>-production-<app-version>/", record)
        self.assertIn("db-integration:", workflow)
        self.assertIn("workflow_dispatch", alert_workflow)
        self.assertIn("upload-artifact", alert_workflow)


if __name__ == "__main__":
    unittest.main()
