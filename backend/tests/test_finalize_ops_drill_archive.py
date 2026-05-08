from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock


class FinalizeOpsDrillArchiveTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts/ops/finalize_ops_drill_archive.py"

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("finalize_ops_drill_archive", cls.SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load {cls.SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.finalizer = module

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
        for label, value in rows.items():
            lines.append(f"| {label} | {value} |")
        return "\n".join(lines)

    def _write_archive(
        self,
        archive_dir: Path,
        ci_markdown: str | None = None,
        alert_markdown: str | None = None,
    ) -> None:
        raw_ci = archive_dir / "raw" / "ci-deployment-drill-record"
        raw_alert = archive_dir / "raw" / "alert-webhook-drill-record"
        completed = archive_dir / "completed"
        raw_ci.mkdir(parents=True)
        raw_alert.mkdir(parents=True)
        completed.mkdir(parents=True)

        if ci_markdown is not None:
            (raw_ci / "ci-deployment-drill-record.md").write_text(ci_markdown, encoding="utf-8")
            (completed / "ci-deployment-drill-record.md").write_text(ci_markdown, encoding="utf-8")
        if alert_markdown is not None:
            (raw_alert / "alert-webhook-drill-record.md").write_text(alert_markdown, encoding="utf-8")
            (completed / "alert-webhook-drill-record.md").write_text(alert_markdown, encoding="utf-8")

        (archive_dir / "README.md").write_text("# Ops Drill Archive\n", encoding="utf-8")
        (archive_dir / "validation.txt").write_text("pending\n", encoding="utf-8")

    def _run_cli(self, archive_dir: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.SCRIPT), str(archive_dir), *extra_args],
            cwd=self.ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def _manifest_entries(self, archive_dir: Path) -> dict[str, str]:
        entries: dict[str, str] = {}
        for line in (archive_dir / "manifest.sha256").read_text(encoding="utf-8").splitlines():
            digest, rel_path = line.split("  ", 1)
            entries[rel_path] = digest
        return entries

    def _sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _package_paths(self, archive_dir: Path) -> tuple[Path, Path]:
        package = archive_dir.parent / f"{archive_dir.name}.zip"
        return package, Path(f"{package}.sha256")

    def _rewrite_package_digest(self, package: Path) -> None:
        package.with_suffix(package.suffix + ".sha256").write_text(
            f"{self._sha256(package)}  {package.name}\n",
            encoding="utf-8",
        )

    def test_finalize_writes_validation_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            result = self.finalizer.finalize_archive(archive_dir)

            validation_text = result.validation_file.read_text(encoding="utf-8")
            manifest_entries = self._manifest_entries(archive_dir)
            package, package_digest = self._package_paths(archive_dir)
            produced_files = {
                result.manifest_file,
                result.manifest_json_file,
                result.seal_file,
                result.package_file,
                result.package_digest_file,
            }
            existing_files = {path for path in produced_files if path.exists()}

        self.assertIn("Finalized at (UTC):", validation_text)
        self.assertIn("Validator output:", validation_text)
        self.assertIn("OK:", validation_text)
        self.assertEqual(produced_files, existing_files)
        self.assertEqual(package, result.package_file)
        self.assertEqual(package_digest, result.package_digest_file)
        self.assertEqual(
            {
                "raw/ci-deployment-drill-record/ci-deployment-drill-record.md",
                "raw/alert-webhook-drill-record/alert-webhook-drill-record.md",
                "completed/ci-deployment-drill-record.md",
                "completed/alert-webhook-drill-record.md",
                "README.md",
                "validation.txt",
                ".sealed",
                "manifest.json",
            },
            set(manifest_entries),
        )

    def test_manifest_hashes_archive_files_after_validation_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            self.finalizer.finalize_archive(archive_dir)
            manifest_entries = self._manifest_entries(archive_dir)
            package, package_digest = self._package_paths(archive_dir)

            expected = {
                "raw/ci-deployment-drill-record/ci-deployment-drill-record.md": self._sha256(
                    archive_dir / "raw" / "ci-deployment-drill-record" / "ci-deployment-drill-record.md"
                ),
                "raw/alert-webhook-drill-record/alert-webhook-drill-record.md": self._sha256(
                    archive_dir / "raw" / "alert-webhook-drill-record" / "alert-webhook-drill-record.md"
                ),
                "completed/ci-deployment-drill-record.md": self._sha256(
                    archive_dir / "completed" / "ci-deployment-drill-record.md"
                ),
                "completed/alert-webhook-drill-record.md": self._sha256(
                    archive_dir / "completed" / "alert-webhook-drill-record.md"
                ),
                "README.md": self._sha256(archive_dir / "README.md"),
                "validation.txt": self._sha256(archive_dir / "validation.txt"),
                ".sealed": self._sha256(archive_dir / ".sealed"),
                "manifest.json": self._sha256(archive_dir / "manifest.json"),
            }
            package_digest_text = package_digest.read_text(encoding="utf-8")
            expected_package_digest_text = f"{self._sha256(package)}  {package.name}\n"

        self.assertEqual(expected, manifest_entries)
        self.assertEqual(expected_package_digest_text, package_digest_text)

    def test_manifest_json_records_audit_metadata_without_zip_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            self.finalizer.finalize_archive(archive_dir)
            manifest = json.loads((archive_dir / "manifest.json").read_text(encoding="utf-8"))
            files_by_path = {entry["path"]: entry for entry in manifest["files"]}

        self.assertEqual(1, manifest["schema_version"])
        self.assertEqual("ops-drill", manifest["archive"]["archive_name"])
        self.assertRegex(manifest["finalized_at_utc"], r"^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual("completed/ci-deployment-drill-record.md", manifest["records"]["ci"])
        self.assertEqual("completed/alert-webhook-drill-record.md", manifest["records"]["alert"])
        self.assertIn("completed/ci-deployment-drill-record.md", files_by_path)
        self.assertIn("raw/alert-webhook-drill-record/alert-webhook-drill-record.md", files_by_path)
        for entry in files_by_path.values():
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(entry["bytes"], 0)
        self.assertNotIn("ops-drill.zip", json.dumps(manifest))

    def test_zip_package_contains_archive_files_without_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            finalized = self.finalizer.finalize_archive(archive_dir)
            with zipfile.ZipFile(finalized.package_file) as archive:
                raw_names = archive.namelist()
                names = set(raw_names)

        self.assertEqual(len(raw_names), len(set(raw_names)))
        self.assertEqual(
            {
                "ops-drill/README.md",
                "ops-drill/validation.txt",
                "ops-drill/manifest.sha256",
                "ops-drill/manifest.json",
                "ops-drill/.sealed",
                "ops-drill/completed/ci-deployment-drill-record.md",
                "ops-drill/completed/alert-webhook-drill-record.md",
                "ops-drill/raw/ci-deployment-drill-record/ci-deployment-drill-record.md",
                "ops-drill/raw/alert-webhook-drill-record/alert-webhook-drill-record.md",
            },
            names,
        )

    def test_verify_package_file_succeeds_without_extracted_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            finalized = self.finalizer.finalize_archive(archive_dir)
            shutil.rmtree(archive_dir)
            verified = self.finalizer.verify_package_file(finalized.package_file)

        self.assertEqual("ops-drill", verified.archive_name)
        self.assertEqual(finalized.package_file, verified.package_file)
        self.assertEqual(finalized.package_digest_file, verified.package_digest_file)

    def test_verify_package_file_rejects_duplicate_zip_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            finalized = self.finalizer.finalize_archive(archive_dir)
            with zipfile.ZipFile(finalized.package_file, "a", compression=zipfile.ZIP_DEFLATED) as archive:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr("ops-drill/README.md", "tampered\n")
            self._rewrite_package_digest(finalized.package_file)

            with self.assertRaises(self.finalizer.FinalizeArchiveError) as raised:
                self.finalizer.verify_package_file(finalized.package_file)

        self.assertIn("duplicate file entries", self.finalizer.format_issues(raised.exception.issues))

    def test_finalize_cleans_up_partial_outputs_when_packaging_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            with mock.patch.object(self.finalizer, "package_archive", side_effect=OSError("zip failed")):
                with self.assertRaises(OSError):
                    self.finalizer.finalize_archive(archive_dir)

            package, package_digest = self._package_paths(archive_dir)
            self.assertEqual("pending\n", (archive_dir / "validation.txt").read_text(encoding="utf-8"))
            self.assertFalse((archive_dir / "manifest.json").exists())
            self.assertFalse((archive_dir / "manifest.sha256").exists())
            self.assertFalse((archive_dir / ".sealed").exists())
            self.assertFalse(package.exists())
            self.assertFalse(package_digest.exists())

    def test_verify_finalized_archive_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            finalized = self.finalizer.finalize_archive(archive_dir)
            verified = self.finalizer.verify_finalized_archive(archive_dir)

        self.assertEqual(finalized.archive_dir, verified.archive_dir)
        self.assertEqual(finalized.manifest_file, verified.manifest_file)
        self.assertEqual(finalized.manifest_json_file, verified.manifest_json_file)
        self.assertEqual(finalized.package_file, verified.package_file)
        self.assertEqual(finalized.package_digest_file, verified.package_digest_file)

    def test_verify_finalized_archive_rejects_root_debug_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            self.finalizer.finalize_archive(archive_dir)
            (archive_dir / "debug.log").write_text("debug only\n", encoding="utf-8")

            with self.assertRaises(self.finalizer.FinalizeArchiveError) as raised:
                self.finalizer.verify_finalized_archive(archive_dir)

        self.assertIn("unexpected file or directory in archive root", self.finalizer.format_issues(raised.exception.issues))

    def test_sensitive_slack_webhook_in_raw_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())
            leak_file = archive_dir / "raw" / "alert-webhook-drill-record" / "leak.txt"
            leak_file.write_text("https://hooks.slack.com/services/T000/B000/secret", encoding="utf-8")

            with self.assertRaises(self.finalizer.FinalizeArchiveError) as raised:
                self.finalizer.finalize_archive(archive_dir)

        self.assertIn("Slack webhook URL", self.finalizer.format_issues(raised.exception.issues))

    def test_sensitive_token_parameter_in_completed_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            alert = self._alert_record({"接收端": "https://example.com/webhook?token=abc"})
            self._write_archive(archive_dir, self._ci_record(), alert)

            with self.assertRaises(self.finalizer.FinalizeArchiveError) as raised:
                self.finalizer.finalize_archive(archive_dir)

        self.assertIn("token parameter", self.finalizer.format_issues(raised.exception.issues))

    def test_sensitive_webhook_key_and_bearer_values_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())
            (archive_dir / "raw" / "alert-webhook-drill-record" / "feishu.txt").write_text(
                "https://open.feishu.cn/open-apis/bot/v2/hook/abc?key=super-secret",
                encoding="utf-8",
            )
            (archive_dir / "completed" / "bearer.txt").write_text(
                "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
                encoding="utf-8",
            )

            with self.assertRaises(self.finalizer.FinalizeArchiveError) as raised:
                self.finalizer.finalize_archive(archive_dir)

        formatted = self.finalizer.format_issues(raised.exception.issues)
        self.assertIn("Feishu webhook URL", formatted)
        self.assertIn("Bearer token", formatted)
        self.assertIn("raw/alert-webhook-drill-record/feishu.txt", formatted)
        self.assertIn("completed/bearer.txt", formatted)

    def test_already_sealed_archive_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            self.finalizer.finalize_archive(archive_dir)
            with self.assertRaises(self.finalizer.FinalizeArchiveError) as raised:
                self.finalizer.finalize_archive(archive_dir)

        self.assertIn("already sealed", self.finalizer.format_issues(raised.exception.issues))

    def test_validation_failure_fails_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(
                archive_dir,
                self._ci_record({"Final decision": "failed"}),
                self._alert_record(),
            )

            with self.assertRaises(self.finalizer.FinalizeArchiveError) as raised:
                self.finalizer.finalize_archive(archive_dir)

            self.assertFalse((archive_dir / "manifest.sha256").exists())
            self.assertFalse((archive_dir / "manifest.json").exists())
            self.assertFalse((archive_dir / ".sealed").exists())
            package, package_digest = self._package_paths(archive_dir)
            self.assertFalse(package.exists())
            self.assertFalse(package_digest.exists())

        self.assertIn("completed/ci-deployment-drill-record.md", self.finalizer.format_issues(raised.exception.issues))

    def test_cli_returns_zero_for_valid_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            result = self._run_cli(archive_dir)

        self.assertEqual(0, result.returncode)
        self.assertIn("OK: finalized ops drill archive", result.stdout)
        self.assertIn("Manifest:", result.stdout)
        self.assertIn("Manifest JSON:", result.stdout)
        self.assertIn("Seal:", result.stdout)
        self.assertIn("Package:", result.stdout)
        self.assertIn("Package SHA256:", result.stdout)

    def test_cli_writes_summary_json_for_valid_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            summary_file = Path(tmpdir) / "finalize-summary.json"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            result = self._run_cli(archive_dir, "--summary-json", str(summary_file))
            summary = json.loads(summary_file.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode)
        self.assertEqual(1, summary["schema_version"])
        self.assertEqual("finalize", summary["mode"])
        self.assertEqual("ok", summary["status"])
        self.assertEqual("ops-drill", summary["archive_name"])
        self.assertRegex(summary["generated_at_utc"], r"^20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(str(archive_dir.resolve()), summary["paths"]["archive_dir"])
        self.assertTrue(summary["paths"]["validation"].endswith("validation.txt"))
        self.assertTrue(summary["paths"]["manifest"].endswith("manifest.sha256"))
        self.assertTrue(summary["paths"]["manifest_json"].endswith("manifest.json"))
        self.assertTrue(summary["paths"]["seal"].endswith(".sealed"))
        self.assertTrue(summary["paths"]["package"].endswith("ops-drill.zip"))
        self.assertTrue(summary["paths"]["package_sha256"].endswith("ops-drill.zip.sha256"))

    def test_cli_verify_returns_zero_for_finalized_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            self.finalizer.finalize_archive(archive_dir)
            result = subprocess.run(
                [sys.executable, str(self.SCRIPT), "--verify", str(archive_dir)],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode)
        self.assertIn("OK: verified finalized ops drill archive", result.stdout)
        self.assertIn("Package SHA256:", result.stdout)

    def test_cli_verify_writes_summary_json_for_finalized_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            summary_file = Path(tmpdir) / "verify-summary.json"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            self.finalizer.finalize_archive(archive_dir)
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.SCRIPT),
                    "--verify",
                    str(archive_dir),
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
        self.assertEqual("verify", summary["mode"])
        self.assertEqual("ok", summary["status"])
        self.assertEqual("ops-drill", summary["archive_name"])
        self.assertEqual(str(archive_dir.resolve()), summary["paths"]["archive_dir"])
        self.assertTrue(summary["paths"]["package_sha256"].endswith("ops-drill.zip.sha256"))

    def test_cli_verify_package_returns_zero_for_zip_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            finalized = self.finalizer.finalize_archive(archive_dir)
            shutil.rmtree(archive_dir)
            result = subprocess.run(
                [sys.executable, str(self.SCRIPT), "--verify-package", str(finalized.package_file)],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(0, result.returncode)
        self.assertIn("OK: verified finalized ops drill package", result.stdout)
        self.assertIn("Archive root:", result.stdout)

    def test_cli_verify_package_writes_summary_json_for_zip_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            summary_file = Path(tmpdir) / "package-summary.json"
            self._write_archive(archive_dir, self._ci_record(), self._alert_record())

            finalized = self.finalizer.finalize_archive(archive_dir)
            shutil.rmtree(archive_dir)
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.SCRIPT),
                    "--verify-package",
                    str(finalized.package_file),
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
        self.assertEqual("verify-package", summary["mode"])
        self.assertEqual("ok", summary["status"])
        self.assertEqual("ops-drill", summary["archive_name"])
        self.assertEqual(str(finalized.package_file), summary["paths"]["package"])
        self.assertEqual(str(finalized.package_digest_file), summary["paths"]["package_sha256"])

    def test_cli_returns_one_for_content_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            self._write_archive(archive_dir, self._ci_record(), None)

            result = self._run_cli(archive_dir)

        self.assertEqual(1, result.returncode)
        self.assertIn("alert-webhook-drill-record.md", result.stderr)

    def test_cli_writes_summary_json_for_content_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            summary_file = Path(tmpdir) / "failure-summary.json"
            self._write_archive(archive_dir, self._ci_record(), None)

            result = self._run_cli(archive_dir, "--summary-json", str(summary_file))
            summary = json.loads(summary_file.read_text(encoding="utf-8"))

        self.assertEqual(1, result.returncode)
        self.assertEqual("finalize", summary["mode"])
        self.assertEqual("failed", summary["status"])
        self.assertGreaterEqual(summary["issue_count"], 1)
        self.assertIn("issues", summary)
        self.assertIn("scope", summary["issues"][0])
        self.assertIn("message", summary["issues"][0])
        self.assertIn("alert-webhook-drill-record.md", json.dumps(summary, ensure_ascii=False))

    def test_cli_returns_two_for_operational_failure(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(self.finalizer, "finalize_archive", side_effect=OSError("disk full")):
            with contextlib.redirect_stderr(stderr):
                code = self.finalizer.main(["archive"])

        self.assertEqual(2, code)
        self.assertIn("disk full", stderr.getvalue())

    def test_cli_writes_summary_json_for_operational_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_file = Path(tmpdir) / "error-summary.json"
            stderr = io.StringIO()
            with mock.patch.object(self.finalizer, "finalize_archive", side_effect=OSError("disk full")):
                with contextlib.redirect_stderr(stderr):
                    code = self.finalizer.main(["archive", "--summary-json", str(summary_file)])

            summary = json.loads(summary_file.read_text(encoding="utf-8"))

        self.assertEqual(2, code)
        self.assertEqual("finalize", summary["mode"])
        self.assertEqual("error", summary["status"])
        self.assertIn("disk full", summary["error"])
        self.assertIn("disk full", stderr.getvalue())

    def test_parse_args_accepts_summary_json_for_all_modes(self) -> None:
        finalized = self.finalizer.parse_args(["archive", "--summary-json", "summary.json"])
        verified = self.finalizer.parse_args(["--verify", "archive", "--summary-json", "verify.json"])
        package = self.finalizer.parse_args(
            ["--verify-package", "archive.zip", "--summary-json", "package.json"]
        )

        self.assertEqual("summary.json", finalized.summary_json)
        self.assertEqual("verify.json", verified.summary_json)
        self.assertEqual("package.json", package.summary_json)
        self.assertEqual("archive.zip", package.verify_package)

    def test_parse_args_preserves_verify_package_conflicts_with_summary_json(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                self.finalizer.parse_args(
                    ["archive", "--verify-package", "archive.zip", "--summary-json", "summary.json"]
                )
            with self.assertRaises(SystemExit):
                self.finalizer.parse_args(
                    ["--verify", "--verify-package", "archive.zip", "--summary-json", "summary.json"]
                )

    def test_parse_args_rejects_summary_json_inside_archive_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            archive_dir = Path(tmpdir) / "ops-drill"
            summary_inside = archive_dir / "summary.json"
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.finalizer.parse_args([str(archive_dir), "--summary-json", str(summary_inside)])


if __name__ == "__main__":
    unittest.main()
