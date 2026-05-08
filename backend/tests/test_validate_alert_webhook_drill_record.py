from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ValidateAlertWebhookDrillRecordTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts/ops/validate_alert_webhook_drill_record.py"

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("validate_alert_webhook_drill_record", cls.SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load {cls.SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.validator = module

    def _valid_rows(self) -> dict[str, str]:
        return {
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

    def _record(
        self,
        overrides: dict[str, str] | None = None,
        omit: set[str] | None = None,
        extra_lines: list[str] | None = None,
    ) -> str:
        rows = self._valid_rows()
        if overrides:
            rows.update(overrides)
        omit = omit or set()

        lines = [
            "# Alert Webhook Drill Record",
            "",
            "| Field | Value |",
            "| --- | --- |",
        ]
        for label in (
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
            if label not in omit:
                lines.append(f"| {label} | {rows[label]} |")
        if extra_lines:
            lines.extend(["", *extra_lines])
        return "\n".join(lines)

    def _run_cli(self, markdown: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmpdir:
            record_path = Path(tmpdir) / "alert-webhook-drill-record.md"
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
            self._record({"负责人": "", "接收端": "待填写", "收到时间": "-"})
        )

        fields = [issue.field for issue in issues]
        self.assertIn("负责人", fields)
        self.assertIn("接收端", fields)
        self.assertIn("收到时间", fields)

    def test_missing_required_row_is_reported(self) -> None:
        issues = self.validator.validate_markdown(self._record(omit={"恢复告警"}))

        self.assertIn(
            ("恢复告警", "missing required field"),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_non_pass_conclusion_is_reported(self) -> None:
        issues = self.validator.validate_markdown(self._record({"结论": "需跟进，暂不通过"}))

        self.assertIn(
            ("结论", "conclusion must explicitly pass"),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_send_false_in_table_is_reported(self) -> None:
        issues = self.validator.validate_markdown(
            self._record({"`send` mode": "false"})
        )

        self.assertIn(
            ("`send` mode", "alert webhook drill must run with send=true, not dry-run"),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_missing_real_send_mode_is_reported(self) -> None:
        issues = self.validator.validate_markdown(self._record({"`send` mode": "manual run"}))

        self.assertIn(
            ("`send` mode", "alert webhook drill must run with send=true, not dry-run"),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_status_must_include_firing_and_resolved(self) -> None:
        issues = self.validator.validate_markdown(self._record({"`status` input": "firing"}))

        self.assertIn(
            ("`status` input", "alert webhook drill must send both firing and resolved payloads"),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_http_response_must_be_successful(self) -> None:
        issues = self.validator.validate_markdown(self._record({"HTTP resolved response": "HTTP 500"}))

        self.assertIn(
            ("HTTP resolved response", "webhook POST must return an HTTP 2xx response"),
            [(issue.field, issue.message) for issue in issues],
        )

    def test_send_false_and_dry_run_text_are_reported(self) -> None:
        issues = self.validator.validate_markdown(
            self._record(extra_lines=["Command: python scripts/ops/alert_webhook_drill.py --dry-run send=false"])
        )

        messages = [issue.message for issue in issues]
        self.assertIn("record contains send=false evidence", messages)
        self.assertIn("record contains dry-run evidence", messages)

    def test_firing_and_resolved_not_received_are_reported(self) -> None:
        issues = self.validator.validate_markdown(
            self._record({"收到时间": "未收到", "恢复告警": "resolved sent, not received"})
        )

        findings = [(issue.field, issue.message) for issue in issues]
        self.assertIn(
            ("收到时间", "firing notification was not confirmed received: 未收到"),
            findings,
        )
        self.assertIn(
            ("恢复告警", "resolved notification was not confirmed received: not received"),
            findings,
        )

    def test_sensitive_webhook_url_is_reported_but_github_url_is_allowed(self) -> None:
        issues = self.validator.validate_markdown(
            self._record(
                extra_lines=[
                    "Run URL: https://github.com/example/repo/actions/runs/123",
                    "Webhook: https://hooks.slack.com/services/T000/B000/secret-token",
                ]
            )
        )

        webhook_issues = [issue for issue in issues if issue.field == "webhook URL"]
        self.assertEqual(1, len(webhook_issues))
        self.assertIn("hooks.slack.com", webhook_issues[0].value)

    def test_escaped_pipes_do_not_break_table_parsing(self) -> None:
        issues = self.validator.validate_markdown(
            self._record({"负责人": "release\\|ops", "接收端": "Feishu\\|release"})
        )

        self.assertEqual([], issues)

    def test_cli_returns_nonzero_and_prints_findings_for_invalid_record(self) -> None:
        result = self._run_cli(self._record({"结论": "failed"}))

        self.assertEqual(1, result.returncode)
        self.assertIn("结论", result.stderr)
        self.assertIn("conclusion must explicitly pass", result.stderr)

    def test_cli_returns_zero_for_valid_record(self) -> None:
        result = self._run_cli(self._record())

        self.assertEqual(0, result.returncode)
        self.assertIn("OK:", result.stdout)


if __name__ == "__main__":
    unittest.main()
