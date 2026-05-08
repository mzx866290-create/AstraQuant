from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class VerifySecretHygieneTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts/verify_secret_hygiene.py"

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("verify_secret_hygiene", cls.SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load {cls.SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.hygiene = module

    def _write_clean_repo(self, root: Path) -> None:
        (root / ".github/workflows").mkdir(parents=True)
        (root / "docs/ops").mkdir(parents=True)
        (root / ".env.production.example").write_text(
            "\n".join(
                (
                    "APP_VERSION=<git-sha-or-semver>",
                    "DB_PASS=<set-by-secret-manager>",
                    "CLICKHOUSE_PASSWORD=<set-by-secret-manager>",
                    "JWT_SECRET=<32-plus-character-random-secret>",
                    "AI_ENCRYPTION_KEY=<fernet-key-from-cryptography>",
                    "TUSHARE_TOKEN=<optional-secret>",
                    "GRAFANA_PASS=<set-by-secret-manager>",
                    "ALERT_WEBHOOK_URL=<real-alert-webhook-url>",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        (root / "docker-compose.prod.yml").write_text(
            "\n".join(
                (
                    "services:",
                    "  postgres:",
                    "    environment:",
                    "      POSTGRES_PASSWORD: ${DB_PASS:?DB_PASS must be set}",
                    "  alertmanager:",
                    "    environment:",
                    "      ALERT_WEBHOOK_URL: ${ALERT_WEBHOOK_URL:?ALERT_WEBHOOK_URL must be set}",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        (root / ".github/workflows/ci.yml").write_text(
            "name: CI\nsteps:\n  - run: python scripts/verify_secret_hygiene.py\n",
            encoding="utf-8",
        )
        (root / ".github/workflows/alert-webhook-drill.yml").write_text(
            "env:\n  ALERT_WEBHOOK_URL: ${{ secrets.ALERT_WEBHOOK_URL }}\n",
            encoding="utf-8",
        )
        for name in (
            "production-deploy.md",
            "monitoring-runbook.md",
            "backup-restore.md",
            "ci-deployment-drill-record.md",
            "ops-drill-archive-runbook.md",
        ):
            (root / "docs/ops" / name).write_text(
                "Use `.env.production` as a filename; do not paste real secrets.\n",
                encoding="utf-8",
            )

    def test_real_repo_passes_default_hygiene_check(self) -> None:
        self.hygiene.verify_secret_hygiene(self.ROOT)

    def test_clean_temp_repo_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_clean_repo(root)

            self.hygiene.verify_secret_hygiene(root)

    def test_rejects_real_secret_in_production_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_clean_repo(root)
            template = root / ".env.production.example"
            template.write_text(template.read_text(encoding="utf-8").replace(
                "JWT_SECRET=<32-plus-character-random-secret>",
                "JWT_SECRET=real-looking-production-secret",
            ), encoding="utf-8")

            with self.assertRaises(self.hygiene.SecretHygieneError) as raised:
                self.hygiene.verify_secret_hygiene(root)

        self.assertIn("JWT_SECRET", self.hygiene.format_issues(raised.exception.issues))

    def test_rejects_weak_production_fallback_and_dangerous_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_clean_repo(root)
            (root / "docker-compose.prod.yml").write_text(
                "POSTGRES_PASSWORD: ${DB_PASS:-changeme}\nGRAFANA_PASS=admin123\n",
                encoding="utf-8",
            )

            with self.assertRaises(self.hygiene.SecretHygieneError) as raised:
                self.hygiene.verify_secret_hygiene(root)

        formatted = self.hygiene.format_issues(raised.exception.issues)
        self.assertIn("${DB_PASS:-changeme}", formatted)
        self.assertIn("admin123", formatted)

    def test_local_env_file_is_checked_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_clean_repo(root)
            (root / ".env.production").write_text("JWT_SECRET=local\n", encoding="utf-8")

            self.hygiene.verify_secret_hygiene(root)
            with self.assertRaises(self.hygiene.SecretHygieneError):
                self.hygiene.verify_secret_hygiene(root, check_local_env=True)

    def test_cli_returns_failure_for_detected_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_clean_repo(root)
            (root / "docs/ops/monitoring-runbook.md").write_text(
                "Webhook https://hooks.slack.com/services/T000/B000/real-token\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(self.SCRIPT), "--root", str(root)],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("Secret hygiene check failed", result.stderr)
        self.assertIn("real-looking webhook URL", result.stderr)

    def test_cli_returns_success_for_clean_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_clean_repo(root)
            result = subprocess.run(
                [sys.executable, str(self.SCRIPT), "--root", str(root)],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode)
        self.assertIn("OK: secret hygiene production surfaces are clean", result.stdout)


if __name__ == "__main__":
    unittest.main()
