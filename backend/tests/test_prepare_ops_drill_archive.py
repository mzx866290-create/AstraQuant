from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class PrepareOpsDrillArchiveTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts/ops/prepare_ops_drill_archive.py"

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("prepare_ops_drill_archive", cls.SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load {cls.SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.preparer = module

    def _write_artifacts(self, root: Path) -> tuple[Path, Path]:
        ci_dir = root / "ci-download" / "ci-deployment-drill-record"
        alert_dir = root / "alert-download" / "alert-webhook-drill-record"
        ci_dir.mkdir(parents=True)
        alert_dir.mkdir(parents=True)
        (ci_dir / "ci-deployment-drill-record.md").write_text("ci record\n", encoding="utf-8")
        (alert_dir / "alert-webhook-drill-record.md").write_text("alert record\n", encoding="utf-8")
        return ci_dir.parent, alert_dir.parent

    def test_prepare_archive_creates_raw_completed_and_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ci_source, alert_source = self._write_artifacts(root)

            prepared = self.preparer.prepare_archive(
                output_root=root / "ops-drills",
                ci_source=ci_source,
                alert_source=alert_source,
                date="2026-05-07",
                environment="production",
                app_version="v1.2.3+abc",
            )

            self.assertEqual("2026-05-07-production-v1.2.3-abc", prepared.archive_dir.name)
            self.assertEqual(
                "ci record\n",
                (prepared.completed_dir / "ci-deployment-drill-record.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "alert record\n",
                (prepared.completed_dir / "alert-webhook-drill-record.md").read_text(encoding="utf-8"),
            )
            self.assertTrue(
                (prepared.archive_dir / "raw/ci-deployment-drill-record/ci-deployment-drill-record.md").exists()
            )
            self.assertTrue(
                (prepared.archive_dir / "raw/alert-webhook-drill-record/alert-webhook-drill-record.md").exists()
            )
            readme = (prepared.archive_dir / "README.md").read_text(encoding="utf-8")
            self.assertIn("finalize_ops_drill_archive.py", readme)
            self.assertIn("manifest.json", readme)
            self.assertIn("manifest.sha256", readme)
            self.assertIn(".sealed", readme)
            self.assertIn("<archive>.zip", readme)
            self.assertIn("<archive>.zip.sha256", readme)
            self.assertTrue(prepared.validation_file.exists())
            self.assertFalse((prepared.archive_dir / "manifest.json").exists())
            self.assertFalse((prepared.archive_dir / "manifest.sha256").exists())
            self.assertFalse((prepared.archive_dir / ".sealed").exists())
            self.assertFalse((prepared.archive_dir.parent / f"{prepared.archive_dir.name}.zip").exists())
            self.assertFalse((prepared.archive_dir.parent / f"{prepared.archive_dir.name}.zip.sha256").exists())

    def test_direct_record_files_are_supported_with_explicit_archive_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ci_file = root / "ci-deployment-drill-record.md"
            alert_file = root / "alert-webhook-drill-record.md"
            ci_file.write_text("ci\n", encoding="utf-8")
            alert_file.write_text("alert\n", encoding="utf-8")

            prepared = self.preparer.prepare_archive(
                output_root=root / "archives",
                ci_source=ci_file,
                alert_source=alert_file,
                date="2026-05-07",
                environment="prod",
                app_version="ignored",
                name="Release 42 / prod",
            )

            self.assertEqual("Release-42-prod", prepared.archive_dir.name)
            self.assertTrue((prepared.completed_dir / "ci-deployment-drill-record.md").exists())
            self.assertTrue((prepared.completed_dir / "alert-webhook-drill-record.md").exists())

    def test_duplicate_records_are_rejected_before_copying(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ci_source, alert_source = self._write_artifacts(root)
            duplicate_dir = ci_source / "another"
            duplicate_dir.mkdir()
            (duplicate_dir / "ci-deployment-drill-record.md").write_text("duplicate\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                self.preparer.prepare_archive(
                    output_root=root / "ops-drills",
                    ci_source=ci_source,
                    alert_source=alert_source,
                    date="2026-05-07",
                    environment="production",
                    app_version="v1",
                )

    def test_default_archive_name_rejects_unknown_app_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ci_source, alert_source = self._write_artifacts(root)

            with self.assertRaisesRegex(ValueError, "app-version"):
                self.preparer.prepare_archive(
                    output_root=root / "ops-drills",
                    ci_source=ci_source,
                    alert_source=alert_source,
                    date="2026-05-07",
                    environment="production",
                    app_version="unknown",
                )

    def test_archive_date_must_be_valid_yyyy_mm_dd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ci_source, alert_source = self._write_artifacts(root)

            with self.assertRaisesRegex(ValueError, "YYYY-MM-DD|calendar date"):
                self.preparer.prepare_archive(
                    output_root=root / "ops-drills",
                    ci_source=ci_source,
                    alert_source=alert_source,
                    date="2026-99-99",
                    environment="production",
                    app_version="v1",
                )

    def test_existing_archive_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ci_source, alert_source = self._write_artifacts(root)
            output_root = root / "ops-drills"

            self.preparer.prepare_archive(
                output_root=output_root,
                ci_source=ci_source,
                alert_source=alert_source,
                date="2026-05-07",
                environment="production",
                app_version="v1",
            )

            with self.assertRaises(FileExistsError):
                self.preparer.prepare_archive(
                    output_root=output_root,
                    ci_source=ci_source,
                    alert_source=alert_source,
                    date="2026-05-07",
                    environment="production",
                    app_version="v1",
                )

            recreated = self.preparer.prepare_archive(
                output_root=output_root,
                ci_source=ci_source,
                alert_source=alert_source,
                date="2026-05-07",
                environment="production",
                app_version="v1",
                force=True,
            )
            self.assertTrue(recreated.archive_dir.exists())

    def test_force_cannot_overwrite_sealed_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ci_source, alert_source = self._write_artifacts(root)
            output_root = root / "ops-drills"

            prepared = self.preparer.prepare_archive(
                output_root=output_root,
                ci_source=ci_source,
                alert_source=alert_source,
                date="2026-05-07",
                environment="production",
                app_version="v1",
            )
            (prepared.archive_dir / ".sealed").write_text("sealed\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                self.preparer.prepare_archive(
                    output_root=output_root,
                    ci_source=ci_source,
                    alert_source=alert_source,
                    date="2026-05-07",
                    environment="production",
                    app_version="v1",
                    force=True,
                )

            self.assertTrue((prepared.archive_dir / ".sealed").exists())
            self.assertTrue((prepared.completed_dir / "ci-deployment-drill-record.md").exists())

    def test_cli_prepares_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ci_source, alert_source = self._write_artifacts(root)
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.SCRIPT),
                    "--ci-record",
                    str(ci_source),
                    "--alert-record",
                    str(alert_source),
                    "--output-root",
                    str(root / "ops-drills"),
                    "--date",
                    "2026-05-07",
                    "--environment",
                    "production",
                    "--app-version",
                    "v1",
                ],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("Prepared ops drill archive", result.stdout)
            self.assertTrue(
                (root / "ops-drills/2026-05-07-production-v1/completed/ci-deployment-drill-record.md").exists()
            )

    def test_cli_returns_nonzero_when_record_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ci_source, _ = self._write_artifacts(root)
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.SCRIPT),
                    "--ci-record",
                    str(ci_source),
                    "--alert-record",
                    str(root / "missing"),
                    "--output-root",
                    str(root / "ops-drills"),
                ],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("ERROR:", result.stderr)


if __name__ == "__main__":
    unittest.main()
