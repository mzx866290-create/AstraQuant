#!/usr/bin/env python3
"""Safely clean generated/runtime artifacts from this repository.

The command defaults to dry-run. Use --apply only after reviewing the list.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


SKIP_TRAVERSAL_DIRS = {
    ".git",
    ".claude",
    ".continue",
    ".idea",
    ".mypy_cache",
    ".venv",
    ".vscode",
    "node_modules",
    "venv",
}

DIRECTORY_NAME_REASONS = {
    "__pycache__": "python bytecode cache",
    ".pytest_cache": "pytest cache",
    "htmlcov": "coverage HTML report",
    "coverage": "coverage output",
    "temp": "temporary workspace",
    "tmp": "temporary workspace",
}

RELATIVE_DIRECTORY_REASONS = {
    Path("frontend/web/dist"): "frontend build output",
    Path("backend/dist"): "backend build output",
}


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    kind: str
    reason: str


@dataclass(frozen=True)
class CleanupReport:
    root: Path
    dry_run: bool
    candidates: tuple[CleanupCandidate, ...]
    removed: tuple[Path, ...]


class CleanupSafetyError(RuntimeError):
    pass


def _resolve_root(root: Path) -> Path:
    resolved = root.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"repository root does not exist: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"repository root must be a directory: {resolved}")
    return resolved


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _file_reason(path: Path) -> str | None:
    name = path.name
    lower_name = name.lower()
    if name == ".coverage" or name.startswith(".coverage."):
        return "coverage data file"
    if lower_name.endswith((".pyc", ".pyo")):
        return "python bytecode file"
    if lower_name.endswith(".log"):
        return "runtime log file"
    if lower_name.endswith((".db", ".sqlite", ".sqlite3")):
        return "local SQLite/runtime database"
    return None


def _directory_reason(path: Path, root: Path) -> str | None:
    relative = path.relative_to(root)
    if relative in RELATIVE_DIRECTORY_REASONS:
        return RELATIVE_DIRECTORY_REASONS[relative]
    return DIRECTORY_NAME_REASONS.get(path.name)


def discover_candidates(root: Path = ROOT) -> tuple[CleanupCandidate, ...]:
    root = _resolve_root(root)
    candidates: list[CleanupCandidate] = []

    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)

        dirnames[:] = sorted(
            dirname for dirname in dirnames if dirname not in SKIP_TRAVERSAL_DIRS
        )
        filenames = sorted(filenames)

        kept_dirnames: list[str] = []
        for dirname in dirnames:
            directory = current_path / dirname
            reason = _directory_reason(directory, root)
            if reason:
                candidates.append(CleanupCandidate(directory, "dir", reason))
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames

        for filename in filenames:
            file_path = current_path / filename
            reason = _file_reason(file_path)
            if reason:
                candidates.append(CleanupCandidate(file_path, "file", reason))

    return tuple(sorted(candidates, key=lambda item: _safe_relative_path(item.path, root)))


def _assert_candidate_is_safe(candidate: CleanupCandidate, root: Path) -> None:
    lexical_path = candidate.path.resolve(strict=False)
    if not _is_within_root(lexical_path, root):
        raise CleanupSafetyError(f"refusing to remove path outside repository: {candidate.path}")
    if lexical_path == root:
        raise CleanupSafetyError("refusing to remove repository root")


def remove_candidates(root: Path, candidates: tuple[CleanupCandidate, ...]) -> tuple[Path, ...]:
    root = _resolve_root(root)
    for candidate in candidates:
        _assert_candidate_is_safe(candidate, root)

    removed: list[Path] = []
    for candidate in sorted(candidates, key=lambda item: len(item.path.parts), reverse=True):
        path = candidate.path
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(path)
    return tuple(sorted(removed, key=lambda path: _safe_relative_path(path.resolve(strict=False), root)))


def cleanup_runtime_artifacts(root: Path = ROOT, *, apply: bool = False) -> CleanupReport:
    root = _resolve_root(root)
    candidates = discover_candidates(root)
    removed = remove_candidates(root, candidates) if apply else ()
    return CleanupReport(root=root, dry_run=not apply, candidates=candidates, removed=removed)


def format_report(report: CleanupReport) -> str:
    mode = "DRY-RUN" if report.dry_run else "APPLY"
    action = "would remove" if report.dry_run else "removed"
    lines = [
        f"{mode}: {action} {len(report.candidates if report.dry_run else report.removed)} runtime artifact path(s)",
        f"Root: {report.root}",
    ]
    for candidate in report.candidates:
        lines.append(
            f"- [{candidate.kind}] {_safe_relative_path(candidate.path, report.root)} ({candidate.reason})"
        )
    if report.dry_run and report.candidates:
        lines.append("Run with --apply to delete these paths.")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean generated/runtime artifacts safely.")
    parser.add_argument("--root", default=str(ROOT), help="Repository root. Defaults to this script's repository.")
    parser.add_argument("--apply", action="store_true", help="Delete matched artifacts. Defaults to dry-run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        report = cleanup_runtime_artifacts(Path(args.root), apply=args.apply)
    except (OSError, CleanupSafetyError) as exc:
        print(f"ERROR: runtime artifact cleanup failed: {exc}", file=sys.stderr)
        return 2
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
