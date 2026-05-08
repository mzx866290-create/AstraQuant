#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType


CI_RECORD = "ci-deployment-drill-record.md"
ALERT_RECORD = "alert-webhook-drill-record.md"


@dataclass(frozen=True)
class SmokeResult:
    workspace: Path
    archive_dir: Path
    package_file: Path
    package_digest_file: Path
    finalize_summary_file: Path
    verify_summary_file: Path
    package_summary_file: Path
    cleaned: bool


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _prepare_module() -> ModuleType:
    return _load_module("prepare_ops_drill_archive", _script_dir() / "prepare_ops_drill_archive.py")


def _finalize_module() -> ModuleType:
    return _load_module("finalize_ops_drill_archive", _script_dir() / "finalize_ops_drill_archive.py")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _new_workspace(work_root: Path | None) -> Path:
    if work_root is None:
        return Path(tempfile.mkdtemp(prefix="ops-drill-smoke-"))
    work_root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"ops-drill-smoke-{_utc_stamp()}-", dir=work_root))


def _ci_record() -> str:
    rows = {
        "Drill date (UTC)": "2026-05-07T00:00:00Z",
        "Owner": "release-ops",
        "Repository": "example/repo",
        "Commit SHA": "abc123def456",
        "APP_VERSION": "smoke.2026.05.07",
        "Environment": "smoke-local",
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
        "Receiver": "release smoke channel",
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
        "Previous known-good APP_VERSION": "smoke.previous",
        "Rollback command rehearsed": "passed",
        "Database migration rollback needed": "no migration rollback needed",
        "Rollback owner confirmed": "release-ops",
        "Production-ready conclusion": "production-ready pass",
        "Blocking issues": "none",
        "Follow-up owner": "none",
        "Follow-up due date": "none",
    }
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
        lines.extend(f"| {label} | {rows[label]} |" for label in labels)
        lines.append("")
    return "\n".join(lines)


def _alert_record() -> str:
    rows = {
        "时间": "2026-05-07T08:00:00Z",
        "负责人": "release-ops",
        "接收端": "release smoke channel",
        "GitHub Actions run URL": "https://github.com/example/repo/actions/runs/124",
        "`send` mode": "true",
        "`status` input": "both",
        "HTTP firing response": "HTTP 200",
        "HTTP resolved response": "HTTP 200",
        "触发告警": "firing payload sent and received, HTTP 200",
        "收到时间": "2026-05-07T08:00:11Z",
        "恢复告警": "resolved payload sent and received at 2026-05-07T08:01:10Z",
        "Artifact `alert-webhook-drill-record`": "uploaded",
        "结论": "通过，firing and resolved were received and the record can be archived",
    }
    lines = ["# Alert Webhook Drill Record", "", "| Field | Value |", "| --- | --- |"]
    lines.extend(f"| {label} | {value} |" for label, value in rows.items())
    return "\n".join(lines) + "\n"


def _write_sample_artifacts(workspace: Path) -> tuple[Path, Path]:
    ci_dir = workspace / "artifacts" / "ci-deployment-drill-record"
    alert_dir = workspace / "artifacts" / "alert-webhook-drill-record"
    ci_dir.mkdir(parents=True, exist_ok=True)
    alert_dir.mkdir(parents=True, exist_ok=True)
    (ci_dir / CI_RECORD).write_text(_ci_record(), encoding="utf-8")
    (alert_dir / ALERT_RECORD).write_text(_alert_record(), encoding="utf-8")
    return ci_dir.parent, alert_dir.parent


def run_smoke(
    *,
    work_root: Path | None = None,
    keep: bool = False,
    date: str = "2026-05-07",
    environment: str = "smoke-local",
    app_version: str = "smoke",
    archive_name: str = "ops-drill-smoke",
) -> SmokeResult:
    workspace = _new_workspace(work_root)
    try:
        prepare = _prepare_module()
        finalize = _finalize_module()
        ci_source, alert_source = _write_sample_artifacts(workspace)

        prepared = prepare.prepare_archive(
            output_root=workspace / "ops-drills",
            ci_source=ci_source,
            alert_source=alert_source,
            date=date,
            environment=environment,
            app_version=app_version,
            name=archive_name,
        )

        summary_dir = workspace / "summaries"
        summary_dir.mkdir()
        finalize_summary = summary_dir / "finalize-summary.json"
        verify_summary = summary_dir / "verify-summary.json"
        package_summary = summary_dir / "package-verify-summary.json"

        finalized = finalize.finalize_archive(prepared.archive_dir)
        finalize.write_summary_json(str(finalize_summary), finalize._success_summary("finalize", finalized))

        verified = finalize.verify_finalized_archive(prepared.archive_dir)
        finalize.write_summary_json(str(verify_summary), finalize._success_summary("verify", verified))

        verified_package = finalize.verify_package_file(finalized.package_file)
        finalize.write_summary_json(
            str(package_summary),
            finalize._success_summary("verify-package", verified_package),
        )

        result = SmokeResult(
            workspace=workspace,
            archive_dir=prepared.archive_dir,
            package_file=finalized.package_file,
            package_digest_file=finalized.package_digest_file,
            finalize_summary_file=finalize_summary,
            verify_summary_file=verify_summary,
            package_summary_file=package_summary,
            cleaned=not keep,
        )
        return result
    except Exception:
        if not keep:
            shutil.rmtree(workspace, ignore_errors=True)
        raise
    finally:
        if not keep and workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a local prepare/finalize/verify smoke test for ops drill archive scripts."
    )
    parser.add_argument("--work-root", help="Parent directory for the smoke workspace. Defaults to a temp directory.")
    parser.add_argument("--keep", action="store_true", help="Keep the smoke workspace for inspection.")
    parser.add_argument("--date", default="2026-05-07", help="Sample drill date.")
    parser.add_argument("--environment", default="smoke-local", help="Sample environment.")
    parser.add_argument("--app-version", default="smoke", help="Sample app version.")
    parser.add_argument("--archive-name", default="ops-drill-smoke", help="Sample archive name.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        result = run_smoke(
            work_root=Path(args.work_root) if args.work_root else None,
            keep=args.keep,
            date=args.date,
            environment=args.environment,
            app_version=args.app_version,
            archive_name=args.archive_name,
        )
    except Exception as exc:
        print(f"ERROR: ops drill archive smoke failed: {exc}", file=sys.stderr)
        return 1

    print("OK: ops drill archive smoke passed")
    print(f"Workspace: {result.workspace}")
    print(f"Archive: {result.archive_dir}")
    print(f"Package: {result.package_file}")
    print(f"Package SHA256: {result.package_digest_file}")
    print(f"Finalize summary: {result.finalize_summary_file}")
    print(f"Verify summary: {result.verify_summary_file}")
    print(f"Package verify summary: {result.package_summary_file}")
    print(f"Workspace kept: {'yes' if not result.cleaned else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
