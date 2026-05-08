from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class VerifyOpsDrillReadinessTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts/ops/verify_ops_drill_readiness.py"

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("verify_ops_drill_readiness", cls.SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load {cls.SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.readiness = module

    def _write_env_file(self, directory: Path, *, placeholder: bool = False) -> Path:
        env_file = directory / ".env.production"
        values = {
            "DB_NAME": "stock_platform",
            "DB_USER": "stockadmin",
            "DB_PASS": "super-secret-pass",
            "CLICKHOUSE_PASSWORD": "clickhouse-secret",
            "APP_IMAGE_REGISTRY": "ghcr.io/example/stock-platform",
            "APP_VERSION": "2026.05.07+abc123",
            "ALERT_WEBHOOK_URL": "https://alerts.example.invalid/webhook",
            "GRAFANA_PASS": "grafana-secret",
            "JWT_SECRET": "jwt-secret-32-plus-chars",
            "AI_ENCRYPTION_KEY": "fernet-key-value",
        }
        if placeholder:
            values["APP_VERSION"] = "<git-sha-or-semver>"

        env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
        return env_file

    def test_verify_readiness_succeeds_on_repo_root_without_env_file(self) -> None:
        result = self.readiness.verify_readiness(self.ROOT)

        self.assertEqual(self.ROOT.resolve(), result.root)
        self.assertGreater(result.checked_files, 0)
        self.assertGreater(result.checked_tokens, 0)
        self.assertEqual(0, result.checked_env_keys)

    def test_verify_readiness_succeeds_with_valid_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = self._write_env_file(Path(tmpdir))
            result = self.readiness.verify_readiness(self.ROOT, env_file=env_file)

        self.assertEqual(self.ROOT.resolve(), result.root)
        self.assertGreater(result.checked_files, 0)
        self.assertGreater(result.checked_tokens, 0)
        self.assertEqual(len(self.readiness.REQUIRED_PRODUCTION_ENV_KEYS), result.checked_env_keys)

    def test_verify_readiness_rejects_placeholder_env_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = self._write_env_file(Path(tmpdir), placeholder=True)
            with self.assertRaises(self.readiness.ReadinessError) as raised:
                self.readiness.verify_readiness(self.ROOT, env_file=env_file)

        formatted = self.readiness.format_issues(raised.exception.issues)
        self.assertIn("production env key still uses a placeholder", formatted)
        self.assertIn("APP_VERSION", formatted)

    def test_cli_writes_summary_json_for_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            env_file = self._write_env_file(tmp)
            summary_file = tmp / "summary.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.SCRIPT),
                    "--root",
                    str(self.ROOT),
                    "--env-file",
                    str(env_file),
                    "--summary-json",
                    str(summary_file),
                ],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            summary = json.loads(summary_file.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode)
        self.assertIn("OK: ops drill readiness prerequisites are present", result.stdout)
        self.assertEqual("ok", summary["status"])
        self.assertEqual(str(self.ROOT.resolve()), summary["root"])
        self.assertEqual(len(self.readiness.REQUIRED_PRODUCTION_ENV_KEYS), summary["checked_env_keys"])
        self.assertGreater(summary["checked_files"], 0)
        self.assertGreater(summary["checked_tokens"], 0)

    def test_cli_writes_summary_json_for_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            env_file = self._write_env_file(tmp, placeholder=True)
            summary_file = tmp / "summary.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.SCRIPT),
                    "--root",
                    str(self.ROOT),
                    "--env-file",
                    str(env_file),
                    "--summary-json",
                    str(summary_file),
                ],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            summary = json.loads(summary_file.read_text(encoding="utf-8"))

        self.assertEqual(1, result.returncode)
        self.assertIn("Ops drill readiness check failed:", result.stderr)
        self.assertEqual("failed", summary["status"])
        self.assertGreaterEqual(summary["issue_count"], 1)
        self.assertIn("issues", summary)
        self.assertIn("scope", summary["issues"][0])
        self.assertIn("message", summary["issues"][0])

    def test_cli_returns_two_for_missing_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_root = Path(tmpdir) / "missing-root"
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.SCRIPT),
                    "--root",
                    str(missing_root),
                ],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(2, result.returncode)
        self.assertIn("repository root does not exist", result.stderr)


if __name__ == "__main__":
    unittest.main()
