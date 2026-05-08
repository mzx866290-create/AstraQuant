#!/usr/bin/env python
"""Dependency-free backend coverage baseline for CI and delivery checks."""
from __future__ import annotations

import argparse
import ast
import os
import sys
import trace
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_TARGETS = [
    ROOT / "backend" / "shared",
    ROOT / "backend" / "services" / "analysis_service" / "engine",
    ROOT / "backend" / "services" / "data_crawler" / "pipeline",
    ROOT / "backend" / "services" / "market_service" / "app" / "services",
]
DEFAULT_MIN_PERCENT = 70.0


@dataclass(frozen=True)
class FileCoverage:
    path: Path
    covered: int
    executable: int

    @property
    def percent(self) -> float:
        return (self.covered / self.executable * 100.0) if self.executable else 100.0

    @property
    def display_path(self) -> str:
        try:
            return self.path.relative_to(ROOT).as_posix()
        except ValueError:
            return self.path.as_posix()


def executable_lines(path: Path) -> set[int]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return set()

    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.stmt, ast.ExceptHandler)) and hasattr(node, "lineno"):
            lines.add(int(node.lineno))
    return lines


def iter_target_files(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        if target.is_file() and target.suffix == ".py":
            files.append(target.resolve())
            continue
        if target.is_dir():
            files.extend(
                path.resolve()
                for path in target.rglob("*.py")
                if "__pycache__" not in path.parts and path.name != "__init__.py"
            )
    return sorted(set(files))


def run_tests_under_trace() -> trace.CoverageResults:
    ignoredirs = [
        sys.prefix,
        sys.exec_prefix,
        str(ROOT / ".venv"),
        str(ROOT / "venv"),
    ]
    tracer = trace.Trace(count=True, trace=False, ignoredirs=ignoredirs)

    def run_discovered_suite() -> unittest.result.TestResult:
        suite = unittest.TestLoader().discover(str(ROOT / "backend" / "tests"))
        runner = unittest.TextTestRunner(verbosity=1)
        return runner.run(suite)

    result = tracer.runfunc(run_discovered_suite)
    if not result.wasSuccessful():
        raise SystemExit("[coverage] backend tests failed")
    return tracer.results()


def collect_covered_lines(results: trace.CoverageResults) -> dict[Path, set[int]]:
    covered_by_file: dict[Path, set[int]] = {}
    for (filename, lineno), count in results.counts.items():
        if count <= 0:
            continue
        try:
            covered_by_file.setdefault(Path(filename).resolve(), set()).add(int(lineno))
        except OSError:
            continue
    return covered_by_file


def calculate_file_coverages(results: trace.CoverageResults, targets: list[Path]) -> list[FileCoverage]:
    covered_by_file = collect_covered_lines(results)
    files: list[FileCoverage] = []
    for path in iter_target_files(targets):
        executable = executable_lines(path)
        if not executable:
            continue
        covered = executable & covered_by_file.get(path, set())
        files.append(FileCoverage(path=path, covered=len(covered), executable=len(executable)))
    return files


def summarize_coverage(files: list[FileCoverage]) -> tuple[float, int, int]:
    total_executable = sum(item.executable for item in files)
    total_covered = sum(item.covered for item in files)
    percent = (total_covered / total_executable * 100.0) if total_executable else 100.0
    return percent, total_covered, total_executable


def print_file_diagnostics(files: list[FileCoverage], limit: int) -> None:
    if limit <= 0:
        return
    lowest = sorted(files, key=lambda item: (item.percent, -item.executable, item.display_path))[:limit]
    if not lowest:
        return
    print(f"[coverage] lowest covered files (showing {len(lowest)}):")
    for item in lowest:
        print(f"[coverage]   {item.percent:6.2f}% ({item.covered}/{item.executable}) {item.display_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify backend coverage baseline.")
    parser.add_argument(
        "--min-percent",
        type=float,
        default=float(os.getenv("BACKEND_COVERAGE_MIN", str(DEFAULT_MIN_PERCENT))),
        help="Minimum statement coverage percentage for target backend modules.",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="File or directory to include. Defaults to core backend modules.",
    )
    parser.add_argument(
        "--show-files",
        type=int,
        default=int(os.getenv("BACKEND_COVERAGE_SHOW_FILES", "8")),
        help="Print this many lowest-covered target files for diagnostics.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    targets = [Path(value).resolve() for value in args.target] if args.target else DEFAULT_TARGETS
    results = run_tests_under_trace()
    files = calculate_file_coverages(results, targets)
    percent, covered, executable = summarize_coverage(files)
    print(f"[coverage] backend core statement coverage: {percent:.2f}% ({covered}/{executable})")
    print_file_diagnostics(files, args.show_files)
    if percent < args.min_percent:
        print(f"[coverage] required minimum: {args.min_percent:.2f}%")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
