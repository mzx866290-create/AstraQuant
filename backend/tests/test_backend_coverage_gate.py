from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import verify_backend_coverage as coverage_gate


class BackendCoverageGateTests(unittest.TestCase):
    def test_default_minimum_tracks_current_quality_baseline(self) -> None:
        self.assertGreaterEqual(coverage_gate.DEFAULT_MIN_PERCENT, 70.0)

    def test_calculates_file_and_total_coverage_from_trace_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sample.py"
            target.write_text(
                "def alpha():\n"
                "    value = 1\n"
                "    if value:\n"
                "        return value\n"
                "    return 0\n",
                encoding="utf-8",
            )
            results = SimpleNamespace(
                counts={
                    (str(target), 1): 1,
                    (str(target), 2): 1,
                    (str(target), 4): 1,
                }
            )

            files = coverage_gate.calculate_file_coverages(results, [target])
            percent, covered, executable = coverage_gate.summarize_coverage(files)

        self.assertEqual(len(files), 1)
        self.assertEqual(covered, 3)
        self.assertEqual(executable, 5)
        self.assertAlmostEqual(percent, 60.0)
        self.assertAlmostEqual(files[0].percent, 60.0)

    def test_iter_target_files_skips_init_and_pycache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "module.py").write_text("x = 1\n", encoding="utf-8")
            pycache = root / "__pycache__"
            pycache.mkdir()
            (pycache / "cached.py").write_text("x = 2\n", encoding="utf-8")

            files = coverage_gate.iter_target_files([root])

        self.assertEqual([path.name for path in files], ["module.py"])

    def test_run_tests_under_trace_runs_discovery_inside_trace_wrapper(self) -> None:
        events: list[object] = []

        class FakeResult:
            def wasSuccessful(self) -> bool:
                return True

        class FakeTracer:
            def __init__(self, *args, **kwargs) -> None:
                events.append("trace_init")

            def runfunc(self, func, *args, **kwargs):
                events.append("runfunc_enter")
                result = func(*args, **kwargs)
                events.append("runfunc_exit")
                return result

            def results(self):
                events.append("results")
                return SimpleNamespace(counts={})

        class FakeLoader:
            def discover(self, start_dir):
                events.append(("discover", start_dir))
                return "suite"

        class FakeRunner:
            def __init__(self, *args, **kwargs) -> None:
                events.append("runner_init")

            def run(self, suite):
                events.append(("run", suite))
                return FakeResult()

        with patch.object(coverage_gate.trace, "Trace", FakeTracer):
            with patch.object(coverage_gate.unittest, "TestLoader", return_value=FakeLoader()):
                with patch.object(coverage_gate.unittest, "TextTestRunner", FakeRunner):
                    results = coverage_gate.run_tests_under_trace()

        self.assertIsInstance(results, SimpleNamespace)
        self.assertEqual(
            events,
            [
                "trace_init",
                "runfunc_enter",
                ("discover", str(coverage_gate.ROOT / "backend" / "tests")),
                "runner_init",
                ("run", "suite"),
                "runfunc_exit",
                "results",
            ],
        )


if __name__ == "__main__":
    unittest.main()
