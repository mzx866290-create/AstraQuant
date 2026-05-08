#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


CI_RECORD = "ci-deployment-drill-record.md"
ALERT_RECORD = "alert-webhook-drill-record.md"


URL_PATTERN = re.compile(r"https?://[^\s<>\])\"']+")


PLACEHOLDER_VALUES = {
    "",
    "-",
    "--",
    "todo",
    "tbd",
    "pending",
    "unknown",
    "placeholder",
    "fill me",
    "to be filled",
    "待填写",
    "未填写",
}


@dataclass(frozen=True)
class ArchiveIssue:
    scope: str
    message: str
    value: str = ""


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def _validators() -> tuple[ModuleType, ModuleType]:
    script_dir = _script_dir()
    ci_validator = _load_module(
        "validate_ci_deployment_drill_record",
        script_dir / "validate_ci_deployment_drill_record.py",
    )
    alert_validator = _load_module(
        "validate_alert_webhook_drill_record",
        script_dir / "validate_alert_webhook_drill_record.py",
    )
    return ci_validator, alert_validator


def _find_record(archive_dir: Path, filename: str) -> tuple[Path | None, list[ArchiveIssue]]:
    matches = sorted(path for path in archive_dir.rglob(filename) if path.is_file())
    if not matches:
        return None, []
    if len(matches) > 1:
        joined = ", ".join(str(path) for path in matches)
        return None, [ArchiveIssue("archive", f"multiple records found for {filename}", joined)]
    return matches[0], []


def _contains_token(value: str, token: str) -> bool:
    return token.lower() in value.lower()


def _normalize_value(value: str) -> str:
    return " ".join(value.replace("<br>", " ").split()).strip()


def _has_meaningful_value(value: str) -> bool:
    normalized = _normalize_value(value).strip("`").lower()
    return normalized not in PLACEHOLDER_VALUES


def _first_url(value: str) -> str:
    match = URL_PATTERN.search(value)
    if match is None:
        return _normalize_value(value)
    return match.group(0).rstrip(".,;")


def _get_field(fields: dict[str, str], labels: tuple[str, ...]) -> str:
    lowered = {label.lower(): value for label, value in fields.items()}
    for label in labels:
        if label in fields:
            return fields[label]
        match = lowered.get(label.lower())
        if match is not None:
            return match
    return ""


def _cross_check_ci_record(ci_validator: ModuleType, markdown: str) -> list[ArchiveIssue]:
    fields = ci_validator.parse_markdown_tables(markdown)
    issues: list[ArchiveIssue] = []

    uploaded_artifacts = fields.get("Uploaded artifacts", "")
    if not _contains_token(uploaded_artifacts, "ci-deployment-drill-record"):
        issues.append(
            ArchiveIssue(
                "ci-deployment-drill-record",
                "Uploaded artifacts must reference ci-deployment-drill-record",
                uploaded_artifacts,
            )
        )
    if not _contains_token(uploaded_artifacts, "alert-webhook-drill-record"):
        issues.append(
            ArchiveIssue(
                "ci-deployment-drill-record",
                "Uploaded artifacts must reference alert-webhook-drill-record",
                uploaded_artifacts,
            )
        )

    alert_artifact = fields.get("Artifact `alert-webhook-drill-record`", "")
    if not _contains_token(alert_artifact, "alert-webhook-drill-record"):
        issues.append(
            ArchiveIssue(
                "ci-deployment-drill-record",
                "Alert artifact evidence must name alert-webhook-drill-record",
                alert_artifact,
            )
        )

    send_mode = fields.get("`send` mode", "")
    if not ci_validator._is_true_send_mode(send_mode):
        issues.append(
            ArchiveIssue(
                "ci-deployment-drill-record",
                "CI drill record must confirm alert webhook send=true",
                send_mode,
            )
        )

    return issues


def _alert_receiver_labels(alert_validator: ModuleType) -> tuple[str, ...]:
    labels = ["Receiver", "接收端"]
    required_fields = getattr(alert_validator, "REQUIRED_FIELDS", ())
    if len(required_fields) >= 3:
        labels.append(required_fields[2])
    return tuple(labels)


def _cross_check_records(
    ci_validator: ModuleType,
    alert_validator: ModuleType,
    ci_markdown: str,
    alert_markdown: str,
) -> list[ArchiveIssue]:
    issues = _cross_check_ci_record(ci_validator, ci_markdown)
    ci_fields = ci_validator.parse_markdown_tables(ci_markdown)
    alert_fields = alert_validator.parse_markdown_tables(alert_markdown)

    ci_alert_run_url = _first_url(_get_field(ci_fields, ("Alert Webhook Drill run URL",)))
    alert_run_url = _first_url(_get_field(alert_fields, ("GitHub Actions run URL",)))
    if (
        _has_meaningful_value(ci_alert_run_url)
        and _has_meaningful_value(alert_run_url)
        and ci_alert_run_url != alert_run_url
    ):
        issues.append(
            ArchiveIssue(
                "ops-drill-archive",
                "CI record Alert Webhook Drill run URL must match alert record GitHub Actions run URL",
                f"{ci_alert_run_url} != {alert_run_url}",
            )
        )

    ci_receiver = _normalize_value(_get_field(ci_fields, ("Receiver",)))
    alert_receiver = _normalize_value(_get_field(alert_fields, _alert_receiver_labels(alert_validator)))
    if (
        _has_meaningful_value(ci_receiver)
        and _has_meaningful_value(alert_receiver)
        and ci_receiver.lower() != alert_receiver.lower()
    ):
        issues.append(
            ArchiveIssue(
                "ops-drill-archive",
                "CI record receiver must match alert drill receiver",
                f"{ci_receiver} != {alert_receiver}",
            )
        )

    ci_send_mode = _get_field(ci_fields, ("`send` mode", "send mode", "send"))
    alert_send_mode = _get_field(alert_fields, tuple(getattr(alert_validator, "SEND_MODE_FIELDS", ("`send` mode",))))
    if (
        _has_meaningful_value(ci_send_mode)
        and _has_meaningful_value(alert_send_mode)
        and ci_validator._is_true_send_mode(ci_send_mode) != alert_validator._is_true_send_mode(alert_send_mode)
    ):
        issues.append(
            ArchiveIssue(
                "ops-drill-archive",
                "CI record send mode must match alert drill send mode",
                f"{ci_send_mode} != {alert_send_mode}",
            )
        )

    return issues


def validate_archive(archive_dir: Path) -> list[ArchiveIssue]:
    issues: list[ArchiveIssue] = []
    if not archive_dir.exists():
        return [ArchiveIssue("archive", "archive directory does not exist", str(archive_dir))]
    if not archive_dir.is_dir():
        return [ArchiveIssue("archive", "archive path must be a directory", str(archive_dir))]

    ci_path, ci_find_issues = _find_record(archive_dir, CI_RECORD)
    alert_path, alert_find_issues = _find_record(archive_dir, ALERT_RECORD)
    issues.extend(ci_find_issues)
    issues.extend(alert_find_issues)

    if ci_path is None:
        if not ci_find_issues:
            issues.append(ArchiveIssue("archive", f"missing required record: {CI_RECORD}"))
    if alert_path is None:
        if not alert_find_issues:
            issues.append(ArchiveIssue("archive", f"missing required record: {ALERT_RECORD}"))
    if ci_path is None or alert_path is None:
        return issues

    ci_validator, alert_validator = _validators()
    ci_markdown = ci_path.read_text(encoding="utf-8")
    alert_markdown = alert_path.read_text(encoding="utf-8")

    for issue in ci_validator.validate_markdown(ci_markdown):
        issues.append(
            ArchiveIssue(
                CI_RECORD,
                f"{issue.field}: {issue.message}",
                issue.value,
            )
        )
    for issue in alert_validator.validate_markdown(alert_markdown):
        issues.append(
            ArchiveIssue(
                ALERT_RECORD,
                f"{issue.field}: {issue.message}",
                issue.value,
            )
        )

    issues.extend(_cross_check_records(ci_validator, alert_validator, ci_markdown, alert_markdown))
    return issues


def format_issues(issues: list[ArchiveIssue]) -> str:
    lines = ["Ops drill archive validation failed:"]
    for issue in issues:
        suffix = f" (value: {issue.value})" if issue.value else ""
        lines.append(f"- {issue.scope}: {issue.message}{suffix}")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a completed operations drill artifact archive directory."
    )
    parser.add_argument("archive_dir", help="Directory containing downloaded and completed drill artifacts.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    archive_dir = Path(args.archive_dir)
    try:
        issues = validate_archive(archive_dir)
    except OSError as exc:
        print(f"ERROR: cannot read archive {archive_dir}: {exc}", file=sys.stderr)
        return 2

    if issues:
        print(format_issues(issues), file=sys.stderr)
        return 1

    print(f"OK: {archive_dir} contains completed passing ops drill records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
