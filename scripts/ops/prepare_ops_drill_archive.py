#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CI_RECORD = "ci-deployment-drill-record.md"
ALERT_RECORD = "alert-webhook-drill-record.md"


DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNKNOWN_APP_VERSION_VALUES = {
    "",
    "-",
    "--",
    "unknown",
    "todo",
    "tbd",
    "pending",
    "n/a",
    "na",
}


@dataclass(frozen=True)
class PreparedArchive:
    archive_dir: Path
    completed_dir: Path
    validation_file: Path


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _slug_part(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    slug = re.sub(r"-{2,}", "-", slug).strip("-._")
    return slug or "unknown"


def archive_name(date: str, environment: str, app_version: str) -> str:
    return f"{_slug_part(date)}-{_slug_part(environment)}-{_slug_part(app_version)}"


def _validate_date(date: str) -> None:
    if not DATE_PATTERN.fullmatch(date):
        raise ValueError("archive date must use YYYY-MM-DD")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("archive date must be a valid calendar date") from exc


def _validate_archive_metadata(date: str, app_version: str, archive_name_override: str | None) -> None:
    _validate_date(date)
    if archive_name_override is None and app_version.strip().lower() in UNKNOWN_APP_VERSION_VALUES:
        raise ValueError("app-version must be set to a release version unless --archive-name is provided")


def find_record(source: Path, filename: str) -> Path:
    if source.is_file():
        if source.name != filename:
            raise FileNotFoundError(f"{source} is a file but not {filename}")
        return source

    if not source.exists():
        raise FileNotFoundError(f"{source} does not exist")
    if not source.is_dir():
        raise FileNotFoundError(f"{source} is not a file or directory")

    matches = sorted(path for path in source.rglob(filename) if path.is_file())
    if not matches:
        raise FileNotFoundError(f"{filename} not found under {source}")
    if len(matches) > 1:
        joined = ", ".join(str(path) for path in matches)
        raise ValueError(f"multiple {filename} records found under {source}: {joined}")
    return matches[0]


def _copy_record(source: Path, raw_dir: Path, completed_dir: Path, artifact_name: str, filename: str) -> None:
    raw_artifact_dir = raw_dir / artifact_name
    raw_artifact_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, raw_artifact_dir / filename)
    shutil.copy2(source, completed_dir / filename)


def _readme_text(archive_dir: Path, app_version: str, environment: str) -> str:
    return "\n".join(
        [
            "# Ops Drill Archive",
            "",
            f"- Environment: {environment}",
            f"- APP_VERSION: {app_version}",
            f"- Archive: {archive_dir.name}",
            "",
            "## Structure",
            "",
            "- `raw/`: downloaded GitHub artifact contents before manual edits.",
            "- `completed/`: manually completed records that should be validated and archived.",
            "- `validation.txt`: written by `scripts/ops/finalize_ops_drill_archive.py` after validation passes.",
            "- `manifest.json`: written by `scripts/ops/finalize_ops_drill_archive.py` with audit metadata and file hashes.",
            "- `manifest.sha256`: written by `scripts/ops/finalize_ops_drill_archive.py` to make later changes visible.",
            "- `.sealed`: written by `scripts/ops/finalize_ops_drill_archive.py` after the archive is finalized.",
            "- `<archive>.zip` and `<archive>.zip.sha256`: written next to this directory by the finalizer.",
            "",
            "## Finalize",
            "",
            "```bash",
            "python scripts/ops/finalize_ops_drill_archive.py .",
            "```",
            "",
            "Store the completed archive in the release or operations log after finalization passes.",
            "",
        ]
    )


def prepare_archive(
    *,
    output_root: Path,
    ci_source: Path,
    alert_source: Path,
    date: str,
    environment: str,
    app_version: str,
    name: str | None = None,
    force: bool = False,
) -> PreparedArchive:
    ci_record = find_record(ci_source, CI_RECORD)
    alert_record = find_record(alert_source, ALERT_RECORD)
    _validate_archive_metadata(date, app_version, name)

    final_name = _slug_part(name) if name else archive_name(date, environment, app_version)
    archive_dir = output_root / final_name
    raw_dir = archive_dir / "raw"
    completed_dir = archive_dir / "completed"

    if archive_dir.exists():
        if (archive_dir / ".sealed").exists():
            raise FileExistsError(f"{archive_dir} is sealed; create a new archive instead of overwriting it")
        if not force:
            raise FileExistsError(f"{archive_dir} already exists; pass --force to recreate it")
        shutil.rmtree(archive_dir)

    completed_dir.mkdir(parents=True, exist_ok=True)
    _copy_record(ci_record, raw_dir, completed_dir, "ci-deployment-drill-record", CI_RECORD)
    _copy_record(alert_record, raw_dir, completed_dir, "alert-webhook-drill-record", ALERT_RECORD)

    readme = archive_dir / "README.md"
    readme.write_text(_readme_text(archive_dir, app_version, environment), encoding="utf-8")

    validation = archive_dir / "validation.txt"
    validation.write_text(
        "Run `python scripts/ops/finalize_ops_drill_archive.py <archive-dir>` after completing records.\n",
        encoding="utf-8",
    )

    return PreparedArchive(archive_dir=archive_dir, completed_dir=completed_dir, validation_file=validation)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a standard ops drill archive directory.")
    parser.add_argument("--ci-record", required=True, help="Downloaded CI drill artifact directory or record Markdown file.")
    parser.add_argument("--alert-record", required=True, help="Downloaded alert drill artifact directory or record Markdown file.")
    parser.add_argument("--output-root", default="ops-drills", help="Directory that will contain the prepared archive.")
    parser.add_argument("--date", default=_today_utc(), help="Archive date in YYYY-MM-DD. Defaults to today in UTC.")
    parser.add_argument("--environment", default="production", help="Deployment environment name.")
    parser.add_argument(
        "--app-version",
        default=os.getenv("APP_VERSION", "unknown"),
        help="APP_VERSION or release version. Defaults to APP_VERSION from the environment.",
    )
    parser.add_argument("--archive-name", help="Explicit archive directory name. Defaults to date-environment-app-version.")
    parser.add_argument("--force", action="store_true", help="Recreate the archive directory when it already exists.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        prepared = prepare_archive(
            output_root=Path(args.output_root),
            ci_source=Path(args.ci_record),
            alert_source=Path(args.alert_record),
            date=args.date,
            environment=args.environment,
            app_version=args.app_version,
            name=args.archive_name,
            force=args.force,
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Prepared ops drill archive: {prepared.archive_dir}")
    print(f"Complete records in: {prepared.completed_dir}")
    print(f"Validation notes: {prepared.validation_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
