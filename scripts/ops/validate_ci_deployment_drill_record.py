#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


REQUIRED_FIELDS = (
    "Drill date (UTC)",
    "Owner",
    "Repository",
    "Commit SHA",
    "APP_VERSION",
    "Environment",
    "Final decision",
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
    "Alert Webhook Drill run URL",
    "`send` mode",
    "Receiver",
    "Firing notification received at",
    "Resolved notification received at",
    "Artifact `alert-webhook-drill-record`",
    "Deployment smoke",
    "Pull immutable images",
    "Start services",
    "Service status",
    "Market readiness",
    "Analysis metrics",
    "Prometheus readiness",
    "Grafana dashboards loaded",
    "Alertmanager config loaded",
    "Rollback check",
    "Previous known-good APP_VERSION",
    "Rollback command rehearsed",
    "Database migration rollback needed",
    "Rollback owner confirmed",
    "Production-ready conclusion",
    "Blocking issues",
    "Follow-up owner",
    "Follow-up due date",
)


CONCLUSION_FIELDS = (
    "Final decision",
    "Production-ready conclusion",
)


KEY_RESULT_FIELDS = (
    "`db-integration` job result",
    "PostgreSQL smoke result",
    "ClickHouse smoke result",
    "Redis smoke result",
    "Backend unit test result",
    "Backend coverage gate result",
    "Frontend lint/type/build result",
    "Frontend smoke result",
    "`send` mode",
    "Firing notification received at",
    "Resolved notification received at",
    "Artifact `alert-webhook-drill-record`",
    "Deployment smoke",
    "Service status",
    "Market readiness",
    "Analysis metrics",
    "Prometheus readiness",
    "Grafana dashboards loaded",
    "Alertmanager config loaded",
    "Rollback check",
    "Rollback command rehearsed",
    "Rollback owner confirmed",
)


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
    "pass / fail / follow-up required",
    "false / true",
    "feishu / dingtalk / slack / other",
    "no / yes, link plan",
}


BAD_RESULT_PATTERNS = (
    re.compile(r"\bnot[- ]?applicable\b|\bn/a\b", re.IGNORECASE),
    re.compile(r"\bskipped\b", re.IGNORECASE),
    re.compile(r"\bfail(?:ed|ure)?\b", re.IGNORECASE),
    re.compile(r"\bcancell?ed\b", re.IGNORECASE),
    re.compile(r"\berror\b", re.IGNORECASE),
    re.compile(r"\btimed[ -]?out\b", re.IGNORECASE),
    re.compile(r"\btimeout\b", re.IGNORECASE),
    re.compile(r"\bblocked\b", re.IGNORECASE),
    re.compile(r"\bunhealthy\b", re.IGNORECASE),
)


BAD_CONCLUSION_PATTERNS = (
    re.compile(r"\bfail(?:ed|ure)?\b", re.IGNORECASE),
    re.compile(r"\bfollow[- ]?up\b", re.IGNORECASE),
    re.compile(r"\brejected\b", re.IGNORECASE),
    re.compile(r"\bnot\s+pass(?:ed)?\b", re.IGNORECASE),
    re.compile(r"\bnot\s+ready\b", re.IGNORECASE),
    re.compile(r"\bblocked\b", re.IGNORECASE),
    re.compile(r"\bskipped\b", re.IGNORECASE),
    re.compile(r"\bcancell?ed\b", re.IGNORECASE),
)


PASS_CONCLUSION_PATTERNS = (
    re.compile(r"\bpass(?:ed)?\b", re.IGNORECASE),
    re.compile(r"\bsuccess(?:ful|fully)?\b", re.IGNORECASE),
    re.compile(r"\bsucceeded\b", re.IGNORECASE),
    re.compile(r"\bproduction[- ]ready\b", re.IGNORECASE),
    re.compile(r"通过"),
)


SEND_MODE_FIELD = "`send` mode"


NO_BLOCKER_PATTERNS = (
    re.compile(r"^(none|no|n/a|na|not applicable)$", re.IGNORECASE),
    re.compile(r"^no\s+(blocking\s+)?issues?$", re.IGNORECASE),
    re.compile(r"^no\s+blockers?$", re.IGNORECASE),
    re.compile(r"无|没有|无阻塞|无阻断"),
)


NO_FOLLOW_UP_PATTERNS = (
    re.compile(r"^(none|no|n/a|na|not applicable)$", re.IGNORECASE),
    re.compile(r"^no\s+follow[- ]?ups?(\s+(required|needed))?$", re.IGNORECASE),
    re.compile(r"无需跟进|无跟进|暂无跟进"),
)


DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str
    value: str = ""


def _normalize_value(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("<br>", " ")).strip()


def _placeholder_key(value: str) -> str:
    return _normalize_value(value).strip("`").lower()


def is_placeholder(value: str) -> bool:
    normalized = _placeholder_key(value)
    return normalized in PLACEHOLDER_VALUES


def _split_markdown_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None

    inner = stripped[1:]
    if inner.endswith("|"):
        inner = inner[:-1]

    cells: list[str] = []
    buffer: list[str] = []
    escaped = False
    for char in inner:
        if escaped:
            buffer.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)

    if escaped:
        buffer.append("\\")
    cells.append("".join(buffer).strip())
    return cells


def _is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def parse_markdown_tables(markdown: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in markdown.splitlines():
        cells = _split_markdown_row(line)
        if not cells or len(cells) < 2 or _is_separator_row(cells):
            continue

        label, value = cells[0], cells[1]
        if label.lower() in {"field", "check"} and value.lower() in {"value", "evidence", "command / evidence"}:
            continue
        fields[label] = value
    return fields


def _is_pass_conclusion(value: str) -> bool:
    normalized = _normalize_value(value)
    if is_placeholder(normalized):
        return False
    if any(pattern.search(normalized) for pattern in BAD_CONCLUSION_PATTERNS):
        return False
    return any(pattern.search(normalized) for pattern in PASS_CONCLUSION_PATTERNS)


def _bad_result_reason(value: str) -> str | None:
    normalized = _normalize_value(value)
    for pattern in BAD_RESULT_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(0)
    return None


def _is_true_send_mode(value: str) -> bool:
    normalized = _normalize_value(value).lower()
    return bool(
        re.search(r"\btrue\b", normalized)
        or re.search(r"\bsend\s*=\s*true\b", normalized)
        or "实际发送" in normalized
    )


def _matches_any(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    normalized = _normalize_value(value)
    return any(pattern.search(normalized) for pattern in patterns)


def _is_no_blocker_value(value: str) -> bool:
    return _matches_any(value, NO_BLOCKER_PATTERNS)


def _is_no_follow_up_value(value: str) -> bool:
    return _matches_any(value, NO_FOLLOW_UP_PATTERNS)


def _is_date_only(value: str) -> bool:
    normalized = _normalize_value(value)
    if not DATE_ONLY_PATTERN.fullmatch(normalized):
        return False
    try:
        datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _passing_conclusions(fields: dict[str, str]) -> bool:
    return all(_is_pass_conclusion(fields.get(label, "")) for label in CONCLUSION_FIELDS)


def _follow_up_consistency_issues(fields: dict[str, str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    blocking_issues = fields.get("Blocking issues", "")
    if blocking_issues and not _is_no_blocker_value(blocking_issues):
        issues.append(
            ValidationIssue(
                "Blocking issues",
                "passing drill must state no blocking issues",
                blocking_issues,
            )
        )

    owner = fields.get("Follow-up owner", "")
    due_date = fields.get("Follow-up due date", "")
    if not owner or not due_date:
        return issues

    owner_is_none = _is_no_follow_up_value(owner)
    due_date_is_none = _is_no_follow_up_value(due_date)
    if owner_is_none != due_date_is_none:
        issues.append(
            ValidationIssue(
                "Follow-up owner",
                "follow-up owner and due date must both be none/n/a or both be concrete",
                f"{owner} / {due_date}",
            )
        )
    elif not owner_is_none and not _is_date_only(due_date):
        issues.append(
            ValidationIssue(
                "Follow-up due date",
                "follow-up due date must use YYYY-MM-DD when follow-up owner is set",
                due_date,
            )
        )

    return issues


def validate_markdown(markdown: str) -> list[ValidationIssue]:
    fields = parse_markdown_tables(markdown)
    issues: list[ValidationIssue] = []

    for label in REQUIRED_FIELDS:
        if label not in fields:
            issues.append(ValidationIssue(label, "missing required field"))
            continue
        value = fields[label]
        if is_placeholder(value):
            issues.append(ValidationIssue(label, "required field is blank or still uses a placeholder", value))

    for label in CONCLUSION_FIELDS:
        value = fields.get(label, "")
        if value and not _is_pass_conclusion(value):
            issues.append(ValidationIssue(label, "conclusion must explicitly pass", value))

    for label in KEY_RESULT_FIELDS:
        value = fields.get(label, "")
        if not value:
            continue
        if label == SEND_MODE_FIELD and not _is_true_send_mode(value):
            issues.append(ValidationIssue(label, "alert webhook drill must run in real send mode", value))
            continue
        reason = _bad_result_reason(value)
        if reason:
            issues.append(ValidationIssue(label, f"key result contains non-passing status: {reason}", value))

    if _passing_conclusions(fields):
        issues.extend(_follow_up_consistency_issues(fields))

    return issues


def format_issues(issues: list[ValidationIssue]) -> str:
    lines = ["CI deployment drill record validation failed:"]
    for issue in issues:
        suffix = f" (value: {issue.value})" if issue.value else ""
        lines.append(f"- {issue.field}: {issue.message}{suffix}")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a completed CI and deployment drill Markdown record."
    )
    parser.add_argument("record", help="Path to the filled CI deployment drill Markdown record.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    record_path = Path(args.record)
    try:
        markdown = record_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: cannot read {record_path}: {exc}", file=sys.stderr)
        return 2

    issues = validate_markdown(markdown)
    if issues:
        print(format_issues(issues), file=sys.stderr)
        return 1

    print(f"OK: {record_path} is a completed passing CI deployment drill record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
