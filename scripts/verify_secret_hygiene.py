#!/usr/bin/env python3
"""Verify production-facing files do not ship real secrets or weak defaults."""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PLACEHOLDER_KEYS = {
    "APP_VERSION": {"<git-sha-or-semver>"},
    "DB_PASS": {"<set-by-secret-manager>"},
    "CLICKHOUSE_PASSWORD": {"<set-by-secret-manager>"},
    "JWT_SECRET": {"<32-plus-character-random-secret>"},
    "AI_ENCRYPTION_KEY": {"<fernet-key-from-cryptography>"},
    "TUSHARE_TOKEN": {"<optional-secret>", ""},
    "GRAFANA_PASS": {"<set-by-secret-manager>"},
    "ALERT_WEBHOOK_URL": {"<real-alert-webhook-url>"},
}

DANGEROUS_DEFAULTS = (
    "admin123",
    "changeme",
    "dev-only-insecure-jwt-secret-change-me",
    "your-super-secret-jwt-key-change-in-production",
    "password123",
)

PRODUCTION_SURFACE_FILES = (
    ".env.production.example",
    "docker-compose.prod.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/alert-webhook-drill.yml",
    "docs/ops/production-deploy.md",
    "docs/ops/monitoring-runbook.md",
    "docs/ops/backup-restore.md",
    "docs/ops/ci-deployment-drill-record.md",
    "docs/ops/ops-drill-archive-runbook.md",
)

WEAK_FALLBACK_RE = re.compile(r"\$\{(?P<key>[A-Z0-9_]*(?:PASS|PASSWORD|SECRET|TOKEN|KEY|WEBHOOK)[A-Z0-9_]*):-[^}]+\}")
WEBHOOK_URL_RE = re.compile(r"https://(?:hooks\.slack\.com|open\.feishu\.cn|oapi\.dingtalk\.com)/[^\s`'\"<>]+", re.I)


@dataclass(frozen=True)
class HygieneIssue:
    path: str
    message: str
    value: str = ""


class SecretHygieneError(Exception):
    def __init__(self, issues: list[HygieneIssue]) -> None:
        super().__init__("secret hygiene check failed")
        self.issues = issues


def _resolve_root(root: Path) -> Path:
    resolved = root.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"repository root does not exist: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"repository root must be a directory: {resolved}")
    return resolved


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_env_template(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in _read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _production_surface_paths(root: Path) -> list[Path]:
    paths = [root / rel_path for rel_path in PRODUCTION_SURFACE_FILES]
    workflow_dir = root / ".github" / "workflows"
    if workflow_dir.is_dir():
        for workflow in sorted(workflow_dir.glob("*.yml")):
            if workflow not in paths:
                paths.append(workflow)
        for workflow in sorted(workflow_dir.glob("*.yaml")):
            if workflow not in paths:
                paths.append(workflow)
    return [path for path in paths if path.is_file()]


def _template_issues(root: Path) -> list[HygieneIssue]:
    path = root / ".env.production.example"
    if not path.is_file():
        return [HygieneIssue(".env.production.example", "production env template is missing")]

    values = _parse_env_template(path)
    issues: list[HygieneIssue] = []
    for key, allowed_values in REQUIRED_PLACEHOLDER_KEYS.items():
        if key not in values:
            issues.append(HygieneIssue(path.relative_to(root).as_posix(), "required placeholder key is missing", key))
            continue
        if values[key] not in allowed_values:
            issues.append(
                HygieneIssue(
                    path.relative_to(root).as_posix(),
                    "production secret template key must remain a placeholder",
                    key,
                )
            )
    return issues


def _surface_text_issues(root: Path) -> list[HygieneIssue]:
    issues: list[HygieneIssue] = []
    for path in _production_surface_paths(root):
        rel_path = path.relative_to(root).as_posix()
        text = _read_text(path)
        lowered = text.lower()

        for token in DANGEROUS_DEFAULTS:
            if token.lower() in lowered:
                issues.append(HygieneIssue(rel_path, "dangerous default secret token is present", token))

        for match in WEAK_FALLBACK_RE.finditer(text):
            issues.append(
                HygieneIssue(
                    rel_path,
                    "secret-like production env var must use required form without fallback",
                    match.group(0),
                )
            )

        for match in WEBHOOK_URL_RE.finditer(text):
            if "example" not in match.group(0):
                issues.append(HygieneIssue(rel_path, "real-looking webhook URL is present", match.group(0)))
    return issues


def _local_env_issues(root: Path, check_local_env: bool) -> list[HygieneIssue]:
    if not check_local_env:
        return []
    local_env = root / ".env.production"
    if local_env.exists():
        return [HygieneIssue(".env.production", "local production env file must not be present for this check")]
    return []


def verify_secret_hygiene(root: Path = ROOT, *, check_local_env: bool = False) -> None:
    root = _resolve_root(root)
    issues = []
    issues.extend(_template_issues(root))
    issues.extend(_surface_text_issues(root))
    issues.extend(_local_env_issues(root, check_local_env))
    if issues:
        raise SecretHygieneError(issues)


def format_issues(issues: list[HygieneIssue]) -> str:
    lines = ["Secret hygiene check failed:"]
    for issue in issues:
        suffix = f" (value: {issue.value})" if issue.value else ""
        lines.append(f"- {issue.path}: {issue.message}{suffix}")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify production-facing files do not ship secrets.")
    parser.add_argument("--root", default=str(ROOT), help="Repository root. Defaults to this script's repository.")
    parser.add_argument(
        "--check-local-env",
        action="store_true",
        help="Also fail if an ignored local .env.production file is present.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        root = _resolve_root(Path(args.root))
        verify_secret_hygiene(root, check_local_env=args.check_local_env)
    except SecretHygieneError as exc:
        print(format_issues(exc.issues), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: cannot verify secret hygiene: {exc}", file=sys.stderr)
        return 2

    print(f"OK: secret hygiene production surfaces are clean: {root}")
    print(f"Checked files: {len(_production_surface_paths(root))}")
    print(f"Checked placeholder keys: {len(REQUIRED_PLACEHOLDER_KEYS)}")
    print(f"Checked local env file: {'yes' if args.check_local_env else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
