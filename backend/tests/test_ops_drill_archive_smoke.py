from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class OpsDrillArchiveSmokeTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts/ops/ops_drill_archive_smoke.py"

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("ops_drill_archive_smoke", cls.SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load {cls.SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.smoke = module

    def test_run_smoke_keeps_full_archive_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.smoke.run_smoke(work_root=Path(tmpdir), keep=True)
            finalize_summary = json.loads(result.finalize_summary_file.read_text(encoding="utf-8"))
            verify_summary = json.loads(result.verify_summary_file.read_text(encoding="utf-8"))
            package_summary = json.loads(result.package_summary_file.read_text(encoding="utf-8"))

            self.assertTrue(result.workspace.exists())
            self.assertTrue(result.archive_dir.exists())
            self.assertTrue(result.package_file.exists())
            self.assertTrue(result.package_digest_file.exists())
            self.assertFalse(result.cleaned)
            self.assertEqual("ok", finalize_summary["status"])
            self.assertEqual("finalize", finalize_summary["mode"])
            self.assertEqual("ok", verify_summary["status"])
            self.assertEqual("verify", verify_summary["mode"])
            self.assertEqual("ok", package_summary["status"])
            self.assertEqual("verify-package", package_summary["mode"])
            self.assertNotIn(str(result.archive_dir), str(result.finalize_summary_file))

    def test_run_smoke_cleans_workspace_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.smoke.run_smoke(work_root=Path(tmpdir), keep=False)

            self.assertTrue(result.cleaned)
            self.assertFalse(result.workspace.exists())

    def test_cli_smoke_returns_zero_and_cleans_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, str(self.SCRIPT), "--work-root", str(Path(tmpdir))],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode)
            self.assertIn("OK: ops drill archive smoke passed", result.stdout)
            self.assertIn("Workspace kept: no", result.stdout)
            self.assertEqual([], list(Path(tmpdir).iterdir()))

    def test_cli_smoke_keep_retains_workspace_for_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.SCRIPT),
                    "--work-root",
                    str(Path(tmpdir)),
                    "--keep",
                    "--archive-name",
                    "custom-smoke",
                ],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            workspaces = list(Path(tmpdir).iterdir())
            self.assertEqual(0, result.returncode)
            self.assertIn("Workspace kept: yes", result.stdout)
            self.assertEqual(1, len(workspaces))
            self.assertTrue((workspaces[0] / "ops-drills" / "custom-smoke").exists())


if __name__ == "__main__":
    unittest.main()
