from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ValidateOpsDrillArchiveTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts/ops/validate_ops_drill_archive.py"

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("validate_ops_drill_archive", cls.SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load {cls.SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.validator = module

    def _ci_record(self, overrides: dict[str, str] | None = None) -> str:
        rows = {
            "Drill date (UTC)": "2026-05-07T00:00:00Z",
            "Owner": "release-ops",
            "Repository": "example/repo",
            "Commit SHA": "abc123def456",
            "APP_VERSION": "2026.05.07+abc123",
            "Environment": "production",
            "Final decision": "pass",
            "CI workflow run URL": "https://github.com/example/repo/actions/runs/123",
            "`db-integration` job result": "success",
            "PostgreSQL smoke result": "passed",
            "ClickHouse smoke result": "passed",
            "Redis smoke result": "passed",
            "Backend unit test result": "passed",
            "Backend coverage gate result": "passed at 70.51%",
            "Frontend lint/type/build result": "passed",
            "Frontend smoke result": "passed",
            "Uploaded artifacts": "ci-deployment-drill-record, alert-webhook-drill-record",
            "Alert Webhook Drill run URL": "https://github.com/example/repo/actions/runs/124",
            "`send` mode": "true",
            "Receiver": "Feishu release channel",
            "Firing notification received at": "2026-05-07T00:10:00Z",
            "Resolved notification received at": "2026-05-07T00:12:00Z",
            "Artifact `alert-webhook-drill-record`": "alert-webhook-drill-record uploaded",
            "Deployment smoke": "passed",
            "Pull immutable images": "`docker compose pull` completed",
            "Start services": "`docker compose up -d` completed",
            "Service status": "all services healthy",
            "Market readiness": "passed",
            "Analysis metrics": "passed",
            "Prometheus readiness": "passed",
            "Grafana dashboards loaded": "passed",
            "Alertmanager config loaded": "passed",
            "Rollback check": "passed",
            "Previous known-good APP_VERSION": "2026.05.06+def456",
            "Rollback command rehearsed": "passed",
            "Database migration rollback needed": "no migration rollback needed",
            "Rollback owner confirmed": "release-ops",
            "Production-ready conclusion": "production-ready pass",
            "Blocking issues": "none",
            "Follow-up owner": "none",
            "Follow-up due date": "none",
        }
        if overrides:
            rows.update(overrides)

        sections = (
            ("Summary", "Field", "Value", (
                "Drill date (UTC)",
                "Owner",
                "Repository",
                "Commit SHA",
                "APP_VERSION",
                "Environment",
                "Final decision",
            )),
            ("GitHub Actions Evidence", "Check", "Evidence", (
                "CI workflow run URL",
                "`db-integration` job result",
                "PostgreSQL smoke result",
                "ClickHouse smoke result",
                "Redis smoke result",
                "Backend unit test result",
                "Backend coverage gate result",
                "Frontend lint/type/build result",
                "Frontend smoke result",
                "Uploaded artifacts",
            )),
            ("Alert Webhook Drill Evidence", "Check", "Evidence", (
                "Alert Webhook Drill run URL",
                "`send` mode",
                "Receiver",
                "Firing notification received at",
                "Resolved notification received at",
                "Artifact `alert-webhook-drill-record`",
            )),
            ("Deployment Smoke Evidence", "Check", "Command / Evidence", (
                "Deployment smoke",
                "Pull immutable images",
                "Start services",
                "Service status",
                "Market readiness",
                "Analysis metrics",
                "Prometheus readiness",
                "Grafana dashboards loaded",
                "Alertmanager config loaded",
            )),
            ("Rollback Check", "Check", "Evidence", (
                "Rollback check",
                "Previous known-good APP_VERSION",
                "Rollback command rehearsed",
                "Database migration rollback needed",
                "Rollback owner confirmed",
            )),
            ("Result", "Field", "Value", (
                "Production-ready conclusion",
                "Blocking issues",
                "Follow-up owner",
                "Follow-up due date",
            )),
        )

        lines = ["# CI And Deployment Drill Record", ""]
        for title, first_header, second_header, labels in sections:
            lines.extend([f"## {title}", "", f"| {first_header} | {second_header} |", "| --- | --- |"])
            for label in labels:
                lines.append(f"| {label} | {rows[label]} |")
            lines.append("")
        return "\n".join(lines)

    def _alert_record(self, overrides: dict[str, str] | None = None) -> str:
        rows = {
            "时间": "2026-05-07T08:00:00Z",
            "负责人": "release-ops",
            "接收端": "Feishu release channel",
            "GitHub Actions run URL": "https://github.com/example/repo/actions/runs/124",
            "`send` mode": "true",
            "`status` input": "both",
            "HTTP firing response": "HTTP 200",
            "HTTP resolved response": "HTTP 200",
            "触发告警": "firing payload sent, HTTP 200",
            "收到时间": "2026-05-07T08:00:11Z",
            "恢复告警": "resolved payload sent and received at 2026-05-07T08:01:10Z",
            "Artifact `alert-webhook-drill-record`": "uploaded",
            "结论": "通过，firing 和 resolved 均已收到，可归档",
        }
        if overrides:
            rows.update(overrides)

        lines = ["# Alert Webhook Drill Record", "", "| Field | Value |", "| --- | --- |"]
        for label in rows:
            lines.append(f"| {label} | {rows[label]} |")
        return "\n".join(lines)

    def _write_archive(
        self,
        directory: Path,
        ci_markdown: str | None = None,
        alert_markdown: str | None = None,
        nested: bool = False,
    ) -> None:
        target = directory
        if nested:
            target = directory / "downloaded-artifacts"
            target.mkdir()
        if ci_markdown is not None:
            (target / "ci-deployment-drill-record.md").write_text(ci_markdown, encoding="utf-8")
        if alert_markdown is not None:
            (target / "alert-webhook-drill-record.md").write_text(alert_markdown, encoding="utf-8")

    def _run_cli(self, archive_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), str(archive_dir)],
            cwd=self.ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_completed_archive_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            self.assertEqual([], self.validator.validate_archive(archive_dir))

    def test_nested_artifact_directory_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            self._write_archive(archive_dir, self._ci_record(), self._alert_record(), nested=True)

            self.assertEqual([], self.validator.validate_archive(archive_dir))

    def test_duplicate_records_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())
            nested = archive_dir / "raw" / "ci-deployment-drill-record"
            nested.mkdir(parents=True)
            (nested / "ci-deployment-drill-record.md").write_text(self._ci_record(), encoding="utf-8")

            issues = self.validator.validate_archive(archive_dir)

        self.assertIn(
            ("archive", "multiple records found for ci-deployment-drill-record.md"),
            [(issue.scope, issue.message) for issue in issues],
        )

    def test_missing_records_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            self._write_archive(archive_dir, ci_markdown=self._ci_record(), alert_markdown=None)

            issues = self.validator.validate_archive(archive_dir)

        self.assertIn(
            ("archive", "missing required record: alert-webhook-drill-record.md"),
            [(issue.scope, issue.message) for issue in issues],
        )

    def test_child_record_failures_are_prefixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            self._write_archive(
                archive_dir,
                self._ci_record({"Final decision": "failed"}),
                self._alert_record({"结论": "失败"}),
            )

            issues = self.validator.validate_archive(archive_dir)

        scopes = [issue.scope for issue in issues]
        self.assertIn("ci-deployment-drill-record.md", scopes)
        self.assertIn("alert-webhook-drill-record.md", scopes)

    def test_ci_cross_check_requires_both_artifacts_and_real_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            self._write_archive(
                archive_dir,
                self._ci_record(
                    {
                        "Uploaded artifacts": "ci-deployment-drill-record",
                        "Artifact `alert-webhook-drill-record`": "uploaded",
                        "`send` mode": "true",
                    }
                ),
                self._alert_record(),
            )

            issues = self.validator.validate_archive(archive_dir)

        self.assertIn(
            (
                "ci-deployment-drill-record",
                "Uploaded artifacts must reference alert-webhook-drill-record",
            ),
            [(issue.scope, issue.message) for issue in issues],
        )

    def test_archive_cross_check_requires_alert_run_url_to_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            self._write_archive(
                archive_dir,
                self._ci_record({"Alert Webhook Drill run URL": "https://github.com/example/repo/actions/runs/999"}),
                self._alert_record(),
            )

            issues = self.validator.validate_archive(archive_dir)

        self.assertIn(
            (
                "ops-drill-archive",
                "CI record Alert Webhook Drill run URL must match alert record GitHub Actions run URL",
            ),
            [(issue.scope, issue.message) for issue in issues],
        )

    def test_archive_cross_check_requires_receiver_to_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            self._write_archive(
                archive_dir,
                self._ci_record({"Receiver": "Slack incident channel"}),
                self._alert_record(),
            )

            issues = self.validator.validate_archive(archive_dir)

        self.assertIn(
            ("ops-drill-archive", "CI record receiver must match alert drill receiver"),
            [(issue.scope, issue.message) for issue in issues],
        )

    def test_cli_returns_zero_for_valid_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            result = self._run_cli(archive_dir)

        self.assertEqual(0, result.returncode)
        self.assertIn("OK:", result.stdout)

    def test_cli_returns_nonzero_for_invalid_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir)
            self._write_archive(archive_dir, self._ci_record(), None)

            result = self._run_cli(archive_dir)

        self.assertEqual(1, result.returncode)
        self.assertIn("alert-webhook-drill-record.md", result.stderr)


if __name__ == "__main__":
    unittest.main()
