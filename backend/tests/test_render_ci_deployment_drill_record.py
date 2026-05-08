from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RenderCiDeploymentDrillRecordTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts/ops/render_ci_deployment_drill_record.py"

    def _render(self, *args: str, env: dict[str, str] | None = None) -> str:
        process_env = os.environ.copy()
        for key in tuple(process_env):
            if key.startswith("DRILL_") or key.startswith("GITHUB_"):
                process_env.pop(key)
        if env:
            process_env.update(env)

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), *args],
            cwd=self.ROOT,
            env=process_env,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout

    def test_output_contains_all_required_field_labels(self) -> None:
        rendered = self._render(
            "--owner",
            "ops",
            "--repository",
            "example/repo",
            "--commit-sha",
            "abc123",
            "--app-version",
            "2026.05.07",
        )

        for label in (
            "Drill date (UTC)",
            "Owner",
            "Repository",
            "Commit SHA",
            "APP_VERSION",
            "Environment",
            "CI workflow run URL",
            "`db-integration` job result",
            "Alert Webhook Drill run URL",
            "Deployment smoke",
            "Rollback check",
            "Blocking issues",
            "Follow-up owner",
            "Follow-up due date",
        ):
            self.assertIn(label, rendered)

    def test_empty_values_preserve_blank_placeholders(self) -> None:
        rendered = self._render()

        self.assertIn("| Owner |  |", rendered)
        self.assertIn("| CI workflow run URL |  |", rendered)
        self.assertIn("| Blocking issues |  |", rendered)

    def test_github_actions_environment_fallbacks(self) -> None:
        rendered = self._render(
            env={
                "GITHUB_ACTOR": "octo-ops",
                "GITHUB_REPOSITORY": "example/repo",
                "GITHUB_RUN_ID": "123456789",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_SHA": "abc123def456",
            }
        )

        self.assertRegex(
            rendered,
            r"\| Drill date \(UTC\) \| \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z \|",
        )
        self.assertIn("| Owner | octo-ops |", rendered)
        self.assertIn("| Repository | example/repo |", rendered)
        self.assertIn("| Commit SHA | abc123def456 |", rendered)
        self.assertIn("| APP_VERSION | abc123def456 |", rendered)
        self.assertIn(
            "| CI workflow run URL | https://github.com/example/repo/actions/runs/123456789 |",
            rendered,
        )

    def test_cli_and_drill_env_values_override_github_fallbacks(self) -> None:
        rendered = self._render(
            "--owner",
            "cli-owner",
            "--commit-sha",
            "cli-sha",
            env={
                "DRILL_APP_VERSION": "env-version",
                "DRILL_CI_RUN_URL": "https://ci.example/runs/env",
                "DRILL_COMMIT_SHA": "env-sha",
                "DRILL_DATE_UTC": "2026-05-07T01:02:03Z",
                "DRILL_OWNER": "env-owner",
                "DRILL_REPOSITORY": "env/repo",
                "GITHUB_ACTOR": "github-owner",
                "GITHUB_REPOSITORY": "github/repo",
                "GITHUB_RUN_ID": "999",
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_SHA": "github-sha",
            },
        )

        self.assertIn("| Drill date (UTC) | 2026-05-07T01:02:03Z |", rendered)
        self.assertIn("| Owner | cli-owner |", rendered)
        self.assertIn("| Repository | env/repo |", rendered)
        self.assertIn("| Commit SHA | cli-sha |", rendered)
        self.assertIn("| APP_VERSION | env-version |", rendered)
        self.assertIn("| CI workflow run URL | https://ci.example/runs/env |", rendered)

    def test_markdown_table_values_escape_pipes_and_newlines(self) -> None:
        rendered = self._render(
            "--owner",
            "ops|release\nprimary",
            "--blocking-issues",
            "first\r\nsecond|pipe",
        )

        self.assertIn("| Owner | ops\\|release<br>primary |", rendered)
        self.assertIn("| Blocking issues | first<br>second\\|pipe |", rendered)

    def test_output_path_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "ci-drill-record.md"
            stdout = self._render("--owner", "release-ops", "--output", str(output_path))

            self.assertEqual("", stdout)
            self.assertTrue(output_path.exists())
            self.assertIn("| Owner | release-ops |", output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
