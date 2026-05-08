#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REQUIRED_FIELDS = (
    "时间",
    "负责人",
    "接收端",
    "GitHub Actions run URL",
    "`send` mode",
    "`status` input",
    "HTTP firing response",
    "HTTP resolved response",
    "触发告警",
    "收到时间",
    "恢复告警",
    "Artifact `alert-webhook-drill-record`",
    "结论",
)


SEND_MODE_FIELDS = {
    "`send` mode",
    "send mode",
    "send",
    "发送模式",
    "是否发送",
}


FIRING_RECEIVED_FIELDS = (
    "收到时间",
    "Firing notification received at",
    "firing received at",
)


RESOLVED_RECEIVED_FIELDS = (
    "恢复告警",
    "Resolved notification received at",
    "resolved received at",
)


STATUS_FIELDS = (
    "`status` input",
    "status input",
    "status",
)


HTTP_RESPONSE_FIELDS = (
    "HTTP firing response",
    "HTTP resolved response",
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
    "n/a",
    "na",
    "待填写",
    "未填写",
    "暂无",
    "待补充",
}


BAD_DELIVERY_PATTERNS = (
    re.compile(r"\bnot\s+received\b", re.IGNORECASE),
    re.compile(r"\bmissing\b", re.IGNORECASE),
    re.compile(r"\bskipped\b", re.IGNORECASE),
    re.compile(r"\bfail(?:ed|ure)?\b", re.IGNORECASE),
    re.compile(r"\bcancell?ed\b", re.IGNORECASE),
    re.compile(r"\berror\b", re.IGNORECASE),
    re.compile(r"\btimed[ -]?out\b", re.IGNORECASE),
    re.compile(r"\btimeout\b", re.IGNORECASE),
    re.compile(r"未收到|未接收|未触达|未发送|未触发|未恢复|失败|错误|异常|超时|取消|跳过"),
)


BAD_CONCLUSION_PATTERNS = (
    re.compile(r"\bfail(?:ed|ure)?\b", re.IGNORECASE),
    re.compile(r"\bfollow[- ]?up\b", re.IGNORECASE),
    re.compile(r"\bblocked\b", re.IGNORECASE),
    re.compile(r"\bnot\s+pass(?:ed)?\b", re.IGNORECASE),
    re.compile(r"\bnot\s+ready\b", re.IGNORECASE),
    re.compile(r"\brejected\b", re.IGNORECASE),
    re.compile(r"不通过|未通过|失败|阻塞|需跟进|待跟进|不可归档|拒绝"),
)


PASS_CONCLUSION_PATTERNS = (
    re.compile(r"\bpass(?:ed)?\b", re.IGNORECASE),
    re.compile(r"\bsuccess(?:ful|fully)?\b", re.IGNORECASE),
    re.compile(r"\bok\b", re.IGNORECASE),
    re.compile(r"通过|成功|已完成|可归档"),
)


BAD_SEND_PATTERNS = (
    re.compile(r"\bsend\s*=\s*false\b", re.IGNORECASE),
    re.compile(r"\bsend\s*:\s*false\b", re.IGNORECASE),
    re.compile(r"\bsend\s+false\b", re.IGNORECASE),
    re.compile(r"\binputs?\.send\s*==\s*['\"]false['\"]", re.IGNORECASE),
)


DRY_RUN_PATTERNS = (
    re.compile(r"--dry-run\b", re.IGNORECASE),
    re.compile(r"\bdry[-_ ]run\s*[:=]\s*true\b", re.IGNORECASE),
    re.compile(r"\bmode\s*[:=]\s*dry[-_ ]run\b", re.IGNORECASE),
    re.compile(r"\bDRY-RUN\b"),
)


URL_PATTERN = re.compile(r"https?://[^\s<>\])\"']+")
SENSITIVE_URL_HINTS = (
    "access_token=",
    "secret=",
    "token=",
    "key=",
    "webhook",
    "robot/send",
    "/services/",
    "/api/webhooks/",
)
SENSITIVE_HOST_HINTS = (
    "hooks.slack.com",
    "oapi.dingtalk.com",
    "open.feishu.cn",
    "qyapi.weixin.qq.com",
    "discord.com",
    "webhook",
)


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
    return _placeholder_key(value) in PLACEHOLDER_VALUES


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


def _bad_delivery_reason(value: str) -> str | None:
    normalized = _normalize_value(value)
    for pattern in BAD_DELIVERY_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(0)
    return None


def _is_pass_conclusion(value: str) -> bool:
    normalized = _normalize_value(value)
    if is_placeholder(normalized):
        return False
    if any(pattern.search(normalized) for pattern in BAD_CONCLUSION_PATTERNS):
        return False
    return any(pattern.search(normalized) for pattern in PASS_CONCLUSION_PATTERNS)


def _is_false_send_mode(value: str) -> bool:
    normalized = _normalize_value(value).lower()
    if is_placeholder(normalized):
        return False
    if re.search(r"\bfalse\b|\bno\b|未发送|未实际发送|未执行|dry[-_ ]run|dry run", normalized):
        return True
    return False


def _is_true_send_mode(value: str) -> bool:
    normalized = _normalize_value(value).lower()
    return bool(
        re.search(r"\btrue\b", normalized)
        or re.search(r"\bsend\s*=\s*true\b", normalized)
        or "实际发送" in normalized
    )


def _is_both_status(value: str) -> bool:
    normalized = _normalize_value(value).lower()
    return bool(
        re.search(r"\bboth\b", normalized)
        or ("firing" in normalized and "resolved" in normalized)
        or "触发" in normalized and "恢复" in normalized
    )


def _is_http_success(value: str) -> bool:
    normalized = _normalize_value(value)
    return bool(re.search(r"\b(?:HTTP\s*)?2\d\d\b", normalized, re.IGNORECASE))


def _find_pattern(patterns: tuple[re.Pattern[str], ...], text: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def _url_has_leak_risk(url: str) -> bool:
    normalized = url.rstrip(".,;").lower()
    if any(host_hint in normalized for host_hint in SENSITIVE_HOST_HINTS):
        return True
    return any(hint in normalized for hint in SENSITIVE_URL_HINTS)


def _find_sensitive_urls(markdown: str) -> list[str]:
    urls: list[str] = []
    for match in URL_PATTERN.finditer(markdown):
        url = match.group(0).rstrip(".,;")
        if _url_has_leak_risk(url):
            urls.append(url)
    return urls


def _field_values(fields: dict[str, str], labels: tuple[str, ...]) -> list[tuple[str, str]]:
    lowered = {label.lower(): (label, value) for label, value in fields.items()}
    values: list[tuple[str, str]] = []
    for label in labels:
        if label in fields:
            values.append((label, fields[label]))
            continue
        match = lowered.get(label.lower())
        if match is not None:
            values.append(match)
    return values


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

    send_values = _field_values(fields, tuple(SEND_MODE_FIELDS))
    for label, value in send_values:
        if not _is_true_send_mode(value):
            issues.append(ValidationIssue(label, "alert webhook drill must run with send=true, not dry-run", value))
            continue
        if _is_false_send_mode(value):
            issues.append(ValidationIssue(label, "alert webhook drill must run with send=true, not dry-run", value))

    for label, value in _field_values(fields, STATUS_FIELDS):
        if value and not is_placeholder(value) and not _is_both_status(value):
            issues.append(ValidationIssue(label, "alert webhook drill must send both firing and resolved payloads", value))

    for label, value in _field_values(fields, HTTP_RESPONSE_FIELDS):
        if value and not is_placeholder(value) and not _is_http_success(value):
            issues.append(ValidationIssue(label, "webhook POST must return an HTTP 2xx response", value))

    bad_send = _find_pattern(BAD_SEND_PATTERNS, markdown)
    if bad_send:
        issues.append(ValidationIssue("send mode", "record contains send=false evidence", bad_send))

    dry_run = _find_pattern(DRY_RUN_PATTERNS, markdown)
    if dry_run:
        issues.append(ValidationIssue("send mode", "record contains dry-run evidence", dry_run))

    for label, value in _field_values(fields, FIRING_RECEIVED_FIELDS):
        reason = _bad_delivery_reason(value)
        if reason:
            issues.append(ValidationIssue(label, f"firing notification was not confirmed received: {reason}", value))

    for label, value in _field_values(fields, RESOLVED_RECEIVED_FIELDS):
        reason = _bad_delivery_reason(value)
        if reason:
            issues.append(ValidationIssue(label, f"resolved notification was not confirmed received: {reason}", value))

    conclusion = fields.get("结论", "")
    if conclusion and not _is_pass_conclusion(conclusion):
        issues.append(ValidationIssue("结论", "conclusion must explicitly pass", conclusion))

    for url in _find_sensitive_urls(markdown):
        issues.append(ValidationIssue("webhook URL", "record appears to expose a sensitive webhook URL", url))

    return issues


def format_issues(issues: list[ValidationIssue]) -> str:
    lines = ["Alert webhook drill record validation failed:"]
    for issue in issues:
        suffix = f" (value: {issue.value})" if issue.value else ""
        lines.append(f"- {issue.field}: {issue.message}{suffix}")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a completed Alert Webhook Drill Markdown record.")
    parser.add_argument("record", help="Path to the filled Alert Webhook Drill Markdown record.")
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

    print(f"OK: {record_path} is a completed passing alert webhook drill record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
