#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ReadinessIssue:
    scope: str
    message: str
    value: str = ""


@dataclass(frozen=True)
class ReadinessResult:
    root: Path
    checked_files: int
    checked_tokens: int
    checked_env_keys: int = 0


REQUIRED_FILES: tuple[str, ...] = (
    ".github/workflows/ci.yml",
    ".github/workflows/alert-webhook-drill.yml",
    ".env.production.example",
    "docker-compose.prod.yml",
    "docker-compose.test.yml",
    "infra/alertmanager/alertmanager.yml",
    "infra/prometheus/prometheus.yml",
    "infra/prometheus/rules/service-alerts.yml",
    "scripts/verify_db_integration.py",
    "scripts/ops/alert_webhook_drill.py",
    "scripts/ops/render_ci_deployment_drill_record.py",
    "scripts/ops/validate_ci_deployment_drill_record.py",
    "scripts/ops/validate_alert_webhook_drill_record.py",
    "scripts/ops/validate_ops_drill_archive.py",
    "scripts/ops/prepare_ops_drill_archive.py",
    "scripts/ops/finalize_ops_drill_archive.py",
    "scripts/ops/ops_drill_archive_smoke.py",
    "scripts/ops/verify_ops_drill_readiness.py",
    "docs/ops/production-deploy.md",
    "docs/ops/monitoring-runbook.md",
    "docs/ops/ci-deployment-drill-record.md",
    "docs/ops/ops-drill-archive-runbook.md",
)


REQUIRED_TEXT_CHECKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        ".github/workflows/ci.yml",
        (
            "db-integration:",
            "python scripts/verify_db_integration.py --require-docker",
            "verify:",
            "python -m unittest discover backend/tests",
            "python scripts/verify_backend_coverage.py",
            "npm run lint",
            "npm run type-check",
            "npm run test:api-compat",
            "npm run test:data-quality",
            "npm run build",
            "npm run smoke:frontend",
            "ci-drill-record:",
            "needs: [db-integration, verify]",
            "if: always()",
            "render_ci_deployment_drill_record.py --output artifacts/ci-deployment-drill-record.md",
            "upload-artifact",
            "name: ci-deployment-drill-record",
            "if-no-files-found: error",
        ),
    ),
    (
        ".github/workflows/alert-webhook-drill.yml",
        (
            "workflow_dispatch:",
            "send:",
            "status:",
            "ALERT_WEBHOOK_URL: ${{ secrets.ALERT_WEBHOOK_URL }}",
            'test -n "$ALERT_WEBHOOK_URL"',
            "python scripts/ops/alert_webhook_drill.py --send",
            "--record-output artifacts/alert-webhook-drill-record.md",
            "upload-artifact",
            "name: alert-webhook-drill-record",
            "if-no-files-found: error",
        ),
    ),
    (
        "docker-compose.prod.yml",
        (
            "APP_VERSION must be set",
            "ALERT_WEBHOOK_URL: ${ALERT_WEBHOOK_URL:?",
            "--config.expand-env",
            "restart: unless-stopped",
            "infra/grafana/provisioning",
            "infra/alertmanager/alertmanager.yml",
        ),
    ),
    (
        "docker-compose.test.yml",
        (
            "postgres-test:",
            "clickhouse-test:",
            "redis-test:",
            "tmpfs:",
            "infra/postgres/init.sql",
            "infra/clickhouse/init.sql",
        ),
    ),
    (
        ".env.production.example",
        (
            "APP_VERSION=",
            "APP_IMAGE_REGISTRY=",
            "DB_NAME=",
            "DB_USER=",
            "DB_PASS=",
            "CLICKHOUSE_PASSWORD=",
            "ALERT_WEBHOOK_URL=<real-alert-webhook-url>",
            "GRAFANA_PASS=",
            "JWT_SECRET=",
            "AI_ENCRYPTION_KEY=",
        ),
    ),
    (
        "infra/alertmanager/alertmanager.yml",
        (
            "webhook_configs",
            "${ALERT_WEBHOOK_URL}",
            "send_resolved: true",
        ),
    ),
    (
        "scripts/ops/finalize_ops_drill_archive.py",
        (
            "--verify",
            "--verify-package",
            "--summary-json",
            "manifest.json",
            "manifest.sha256",
            ".sealed",
        ),
    ),
    (
        "scripts/ops/ops_drill_archive_smoke.py",
        (
            "prepare_archive",
            "finalize_archive",
            "verify_finalized_archive",
            "verify_package_file",
            "--keep",
        ),
    ),
    (
        "docs/ops/production-deploy.md",
        (
            "python scripts/ops/verify_ops_drill_readiness.py",
            "--env-file .env.production",
            "docker compose -f docker-compose.prod.yml --env-file .env.production",
        ),
    ),
    (
        "docs/ops/ops-drill-archive-runbook.md",
        (
            "gh run download <ci-run-id> -n ci-deployment-drill-record",
            "gh run download <alert-run-id> -n alert-webhook-drill-record",
            "python scripts/ops/verify_ops_drill_readiness.py",
            "python scripts/ops/ops_drill_archive_smoke.py",
            "python scripts/ops/prepare_ops_drill_archive.py",
            "python scripts/ops/finalize_ops_drill_archive.py",
            "python scripts/ops/finalize_ops_drill_archive.py --verify-package",
            "object-lock/WORM",
        ),
    ),
    (
        "docs/ops/ci-deployment-drill-record.md",
        (
            "CI workflow run URL",
            "`db-integration` job result",
            "Alert Webhook Drill run URL",
            "`send` mode",
            "Deployment smoke",
            "Rollback check",
            "Production-ready conclusion",
            "python scripts/ops/verify_ops_drill_readiness.py",
            "python scripts/ops/ops_drill_archive_smoke.py",
        ),
    ),
    (
        "docs/ops/monitoring-runbook.md",
        (
            "ALERT_WEBHOOK_URL",
            "firing",
            "resolved",
            "python scripts/ops/verify_ops_drill_readiness.py",
            "python scripts/ops/validate_alert_webhook_drill_record.py",
            "python scripts/ops/ops_drill_archive_smoke.py",
        ),
    ),
)


REQUIRED_PRODUCTION_ENV_KEYS: tuple[str, ...] = (
    "DB_NAME",
    "DB_USER",
    "DB_PASS",
    "CLICKHOUSE_PASSWORD",
    "APP_IMAGE_REGISTRY",
    "APP_VERSION",
    "ALERT_WEBHOOK_URL",
    "GRAFANA_PASS",
    "JWT_SECRET",
    "AI_ENCRYPTION_KEY",
)


PLACEHOLDER_ENV_VALUES = {
    "",
    "-",
    "--",
    "todo",
    "tbd",
    "pending",
    "unknown",
    "<set-by-secret-manager>",
    "<git-sha-or-semver>",
    "<real-alert-webhook-url>",
    "<32-plus-character-random-secret>",
    "<fernet-key-from-cryptography>",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_text(path: Path) -> tuple[str, ReadinessIssue | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError as exc:
        return "", ReadinessIssue(path.as_posix(), "file must be UTF-8 readable", str(exc))
    except OSError as exc:
        return "", ReadinessIssue(path.as_posix(), "file cannot be read", str(exc))


def _required_file_issues(root: Path) -> list[ReadinessIssue]:
    issues: list[ReadinessIssue] = []
    for rel_path in REQUIRED_FILES:
        path = root / rel_path
        if not path.is_file():
            issues.append(ReadinessIssue(rel_path, "required drill readiness file is missing"))
    return issues


def _token_issues(root: Path) -> list[ReadinessIssue]:
    issues: list[ReadinessIssue] = []
    for rel_path, tokens in REQUIRED_TEXT_CHECKS:
        path = root / rel_path
        if not path.is_file():
            continue
        text, read_issue = _read_text(path)
        if read_issue:
            issues.append(read_issue)
            continue
        for token in tokens:
            if token not in text:
                issues.append(ReadinessIssue(rel_path, "required readiness marker is missing", token))
    return issues


def _resolve_optional_path(root: Path, value: Path | None) -> Path | None:
    if value is None:
        return None
    return value if value.is_absolute() else root / value


def _parse_env_file(path: Path) -> tuple[dict[str, str], ReadinessIssue | None]:
    text, read_issue = _read_text(path)
    if read_issue:
        return {}, read_issue

    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values, None


def _env_file_issues(env_file: Path | None) -> list[ReadinessIssue]:
    if env_file is None:
        return []
    if not env_file.is_file():
        return [ReadinessIssue(env_file.as_posix(), "production env file is missing")]

    values, read_issue = _parse_env_file(env_file)
    if read_issue:
        return [read_issue]

    issues: list[ReadinessIssue] = []
    for key in REQUIRED_PRODUCTION_ENV_KEYS:
        value = values.get(key, "")
        if key not in values:
            issues.append(ReadinessIssue(env_file.as_posix(), "required production env key is missing", key))
        elif value.strip().lower() in PLACEHOLDER_ENV_VALUES or (value.startswith("<") and value.endswith(">")):
            issues.append(ReadinessIssue(env_file.as_posix(), "production env key still uses a placeholder", key))
    return issues


def verify_readiness(root: Path, env_file: Path | None = None) -> ReadinessResult:
    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"repository root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"repository root must be a directory: {root}")

    resolved_env_file = _resolve_optional_path(root, env_file)
    issues = _required_file_issues(root)
    issues.extend(_token_issues(root))
    issues.extend(_env_file_issues(resolved_env_file))
    if issues:
        raise ReadinessError(issues)

    return ReadinessResult(
        root=root,
        checked_files=len(REQUIRED_FILES),
        checked_tokens=sum(len(tokens) for _rel_path, tokens in REQUIRED_TEXT_CHECKS),
        checked_env_keys=len(REQUIRED_PRODUCTION_ENV_KEYS) if resolved_env_file else 0,
    )


class ReadinessError(Exception):
    def __init__(self, issues: list[ReadinessIssue]) -> None:
        super().__init__("ops drill readiness check failed")
        self.issues = issues


def format_issues(issues: list[ReadinessIssue]) -> str:
    lines = ["Ops drill readiness check failed:"]
    for issue in issues:
        suffix = f" (value: {issue.value})" if issue.value else ""
        lines.append(f"- {issue.scope}: {issue.message}{suffix}")
    return "\n".join(lines)


def _summary_payload(status: str, result: ReadinessResult | None = None, issues: list[ReadinessIssue] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "generated_at_utc": _utc_now(),
        "status": status,
    }
    if result:
        payload["root"] = str(result.root)
        payload["checked_files"] = result.checked_files
        payload["checked_tokens"] = result.checked_tokens
        payload["checked_env_keys"] = result.checked_env_keys
    if issues is not None:
        payload["issue_count"] = len(issues)
        payload["issues"] = [
            {"scope": issue.scope, "message": issue.message, "value": issue.value}
            for issue in issues
        ]
    return payload


def write_summary_json(destination: str | None, payload: dict[str, object]) -> Path | None:
    if not destination:
        return None
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify local prerequisites for a real ops drill.")
    parser.add_argument("--root", default=".", help="Repository root to inspect. Defaults to current directory.")
    parser.add_argument(
        "--env-file",
        help="Optional production env file to check for required non-placeholder keys.",
    )
    parser.add_argument("--summary-json", help="Write a machine-readable readiness summary.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        result = verify_readiness(Path(args.root), Path(args.env_file) if args.env_file else None)
        write_summary_json(args.summary_json, _summary_payload("ok", result=result))
    except ReadinessError as exc:
        try:
            write_summary_json(args.summary_json, _summary_payload("failed", issues=exc.issues))
        except OSError as summary_exc:
            print(format_issues(exc.issues), file=sys.stderr)
            print(f"ERROR: cannot write summary json: {summary_exc}", file=sys.stderr)
            return 2
        print(format_issues(exc.issues), file=sys.stderr)
        return 1
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: cannot verify ops drill readiness: {exc}", file=sys.stderr)
        return 2

    print(f"OK: ops drill readiness prerequisites are present: {result.root}")
    print(f"Checked files: {result.checked_files}")
    print(f"Checked markers: {result.checked_tokens}")
    print(f"Checked env keys: {result.checked_env_keys}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
