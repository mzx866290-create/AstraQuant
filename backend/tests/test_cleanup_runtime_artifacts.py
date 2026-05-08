from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CleanupRuntimeArtifactsTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[2]
    SCRIPT = ROOT / "scripts/cleanup_runtime_artifacts.py"

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("cleanup_runtime_artifacts", cls.SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load {cls.SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.cleanup = module

    def _make_sample_tree(self, root: Path) -> None:
        (root / "backend/shared").mkdir(parents=True)
        (root / "backend/shared/models.py").write_text("class Stock: pass\n", encoding="utf-8")
        (root / "backend/shared/__pycache__").mkdir()
        (root / "backend/shared/__pycache__/models.cpython-311.pyc").write_bytes(b"pyc")

        (root / "frontend/web/dist/assets").mkdir(parents=True)
        (root / "frontend/web/dist/index.html").write_text("<!doctype html>\n", encoding="utf-8")

        (root / "logs").mkdir()
        (root / "logs/service.out.log").write_text("log\n", encoding="utf-8")
        (root / "unit-test.db").write_bytes(b"sqlite")
        (root / ".coverage").write_text("coverage\n", encoding="utf-8")
        (root / "tmp").mkdir()
        (root / "tmp/scratch.txt").write_text("tmp\n", encoding="utf-8")

        (root / "node_modules/pkg").mkdir(parents=True)
        (root / "node_modules/pkg/debug.log").write_text("keep\n", encoding="utf-8")
        (root / ".env.production.example").write_text("JWT_SECRET=<template>\n", encoding="utf-8")

    def test_dry_run_lists_artifacts_without_removing_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_sample_tree(root)

            report = self.cleanup.cleanup_runtime_artifacts(root)
            candidate_paths = {item.path.relative_to(root).as_posix() for item in report.candidates}

            self.assertTrue(report.dry_run)
            self.assertIn("backend/shared/__pycache__", candidate_paths)
            self.assertIn("frontend/web/dist", candidate_paths)
            self.assertIn("logs/service.out.log", candidate_paths)
            self.assertIn("unit-test.db", candidate_paths)
            self.assertIn(".coverage", candidate_paths)
            self.assertIn("tmp", candidate_paths)
            self.assertNotIn("node_modules/pkg/debug.log", candidate_paths)
            self.assertTrue((root / "frontend/web/dist/index.html").exists())
            self.assertTrue((root / "backend/shared/models.py").exists())

    def test_apply_removes_only_generated_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_sample_tree(root)

            report = self.cleanup.cleanup_runtime_artifacts(root, apply=True)

            self.assertFalse(report.dry_run)
            self.assertGreaterEqual(len(report.removed), 5)
            self.assertFalse((root / "backend/shared/__pycache__").exists())
            self.assertFalse((root / "frontend/web/dist").exists())
            self.assertFalse((root / "logs/service.out.log").exists())
            self.assertFalse((root / "unit-test.db").exists())
            self.assertFalse((root / ".coverage").exists())
            self.assertFalse((root / "tmp").exists())
            self.assertTrue((root / "backend/shared/models.py").exists())
            self.assertTrue((root / "node_modules/pkg/debug.log").exists())
            self.assertTrue((root / ".env.production.example").exists())

    def test_remove_candidates_rejects_paths_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            outside = Path(tmpdir) / "outside.log"
            root.mkdir()
            outside.write_text("do not remove\n", encoding="utf-8")
            candidate = self.cleanup.CleanupCandidate(outside, "file", "outside")

            with self.assertRaises(self.cleanup.CleanupSafetyError):
                self.cleanup.remove_candidates(root, (candidate,))

            self.assertTrue(outside.exists())

    def test_cli_defaults_to_dry_run_and_apply_deletes_after_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._make_sample_tree(root)
            dry_run = subprocess.run(
                [sys.executable, str(self.SCRIPT), "--root", str(root)],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, dry_run.returncode)
            self.assertIn("DRY-RUN", dry_run.stdout)
            self.assertIn("Run with --apply", dry_run.stdout)
            self.assertTrue((root / "frontend/web/dist").exists())

            apply = subprocess.run(
                [sys.executable, str(self.SCRIPT), "--root", str(root), "--apply"],
                cwd=self.ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, apply.returncode)
            self.assertIn("APPLY", apply.stdout)
            self.assertFalse((root / "frontend/web/dist").exists())


if __name__ == "__main__":
    unittest.main()
