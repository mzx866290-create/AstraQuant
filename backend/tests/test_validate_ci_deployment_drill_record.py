from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ValidateCiDeploymentDrillRecordTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts/ops/validate_ci_deployment_drill_record.py"

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("validate_ci_deployment_drill_record", cls.SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load {cls.SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.validator = module

    def _valid_rows(self) -> dict[str, str]:
        return {
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
            "Artifact `alert-webhook-drill-record`": "uploaded",
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
            "Database migration rollback needed": "no",
            "Rollback owner confirmed": "release-ops",
            "Production-ready conclusion": "production-ready pass",
            "Blocking issues": "none",
            "Follow-up owner": "none",
            "Follow-up due date": "none",
        }

    def _record(self, overrides: dict[str, str] | None = None, omit: set[str] | None = None) -> str:
        rows = self._valid_rows()
        if overrides:
            rows.update(overrides)
        omit = omit or set()
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
                if label not in omit:
                    lines.append(f"| {label} | {rows[label]} |")
            lines.append("")
        return "\n".join(lines)

    def _run_cli(self, markdown: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmpdir:
            record_path = Path(tmpdir) / "ci-drill.md"
            record_path.write_text(markdown, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(self.SCRIPT), str(record_path)],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_completed_passing_record_is_valid(self) -> None:
        issues = self.validator.validate_markdown(self._record())

        self.assertEqual([], issues)

    def test_blank_required_fields_are_reported(self) -> None:
        issues = self.validator.validate_markdown(
            self._record({"Owner": "", "CI workflow run URL": " ", "Blocking issues": "-"})
        )

        self.assertIn("Owner", [issue.field for issue in issues])
        self.assertIn("CI workflow run URL", [issue.field for issue in issues])
        self.assertIn("Blocking issues", [issue.field for issue in issues])

    def test_documentation_placeholders_are_reported(self) -> None:
        issues = self.validator.validate_markdown(
            self._record(
                {
                    "Final decision": "pass / fail / follow-up required",
                    "`send` mode": "false / true",
                    "Receiver": "Feishu / DingTalk / Slack / other",
                    "Database migration rollback needed": "no / yes, link plan",
                }
            )
        )

        fields = [issue.field for issue in issues]
        self.assertIn("Final decision", fields)
        self.assertIn("`send` mode", fields)
        self.assertIn("Receiver", fields)
        self.assertIn("Database migration rollback needed", fields)

    def test_non_pass_conclusion_is_reported(self) -> None:
        issues = self.validator.validate_markdown(
            self._record({"Production-ready conclusion": "follow-up required"})
        )

        self.assertIn(
            ("Production-ready conclusion", "conclusion must explicitly pass"),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_key_result_failure_statuses_are_reported(self) -> None:
        issues = self.validator.validate_markdown(
            self._record(
                {
                    "`db-integration` job result": "skipped",
                    "Frontend smoke result": "failure",
                    "Deployment smoke": "cancelled",
                    "Rollback check": "not-applicable-ci-record-only",
                }
            )
        )

        fields = [issue.field for issue in issues if "non-passing status" in issue.message]
        self.assertIn("`db-integration` job result", fields)
        self.assertIn("Frontend smoke result", fields)
        self.assertIn("Deployment smoke", fields)
        self.assertIn("Rollback check", fields)

    def test_alert_drill_must_use_real_send_mode(self) -> None:
        issues = self.validator.validate_markdown(self._record({"`send` mode": "false"}))

        self.assertIn(
            ("`send` mode", "alert webhook drill must run in real send mode"),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_pass_conclusion_requires_no_blocking_issues(self) -> None:
        issues = self.validator.validate_markdown(
            self._record({"Blocking issues": "Market smoke still blocked by missing quote data"})
        )

        self.assertIn(
            ("Blocking issues", "passing drill must state no blocking issues"),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_follow_up_owner_and_due_date_must_be_consistent(self) -> None:
        issues = self.validator.validate_markdown(
            self._record({"Follow-up owner": "release-ops", "Follow-up due date": "none"})
        )

        self.assertIn(
            (
                "Follow-up owner",
                "follow-up owner and due date must both be none/n/a or both be concrete",
            ),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_concrete_follow_up_due_date_must_use_date_only_format(self) -> None:
        issues = self.validator.validate_markdown(
            self._record({"Follow-up owner": "release-ops", "Follow-up due date": "next Friday"})
        )

        self.assertIn(
            ("Follow-up due date", "follow-up due date must use YYYY-MM-DD when follow-up owner is set"),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_concrete_nonblocking_follow_up_with_date_is_allowed(self) -> None:
        issues = self.validator.validate_markdown(
            self._record({"Follow-up owner": "release-ops", "Follow-up due date": "2026-05-14"})
        )

        self.assertEqual([], issues)

    def test_missing_required_row_is_reported(self) -> None:
        issues = self.validator.validate_markdown(self._record(omit={"Alertmanager config loaded"}))

        self.assertIn(
            ("Alertmanager config loaded", "missing required field"),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_escaped_pipes_do_not_break_table_parsing(self) -> None:
        issues = self.validator.validate_markdown(
            self._record({"Owner": "release\\|ops", "Uploaded artifacts": "ci\\|alert"})
        )

        self.assertEqual([], issues)

    def test_cli_returns_nonzero_and_prints_findings_for_invalid_record(self) -> None:
        result = self._run_cli(self._record({"Final decision": "failed"}))

        self.assertEqual(1, result.returncode)
        self.assertIn("Final decision", result.stderr)
        self.assertIn("conclusion must explicitly pass", result.stderr)

    def test_cli_returns_zero_for_valid_record(self) -> None:
        result = self._run_cli(self._record())

        self.assertEqual(0, result.returncode)
        self.assertIn("OK:", result.stdout)


if __name__ == "__main__":
    unittest.main()
