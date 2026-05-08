#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import ModuleType


CI_RECORD = "ci-deployment-drill-record.md"
ALERT_RECORD = "alert-webhook-drill-record.md"
MANIFEST = "manifest.sha256"
MANIFEST_JSON = "manifest.json"
VALIDATION = "validation.txt"
SEAL_MARKER = ".sealed"

ROOT_CONTENT_FILES = (
    Path("README.md"),
    Path(VALIDATION),
    Path(SEAL_MARKER),
)
ALLOWED_ROOT_ENTRIES = {
    "raw",
    "completed",
    "README.md",
    VALIDATION,
    MANIFEST_JSON,
    MANIFEST,
    SEAL_MARKER,
}

SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Slack webhook URL", re.compile(r"hooks\.slack\.com/services", re.IGNORECASE)),
    ("Feishu webhook URL", re.compile(r"open\.feishu\.cn/open-apis/bot/v2/hook", re.IGNORECASE)),
    ("DingTalk webhook URL", re.compile(r"oapi\.dingtalk\.com/robot/send", re.IGNORECASE)),
    ("WeCom webhook URL", re.compile(r"qyapi\.weixin\.qq\.com/cgi-bin/webhook/send", re.IGNORECASE)),
    ("Discord webhook URL", re.compile(r"discord(?:app)?\.com/api/webhooks", re.IGNORECASE)),
    ("Bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("Slack bot token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b")),
    ("JWT token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE)),
    ("database connection URL", re.compile(r"\b(?:postgres(?:ql)?|mysql|redis)://[^ \n\r\t]+", re.IGNORECASE)),
    ("access_token parameter", re.compile(r"\baccess_token\s*=", re.IGNORECASE)),
    ("api_key parameter", re.compile(r"\bapi[_-]?key\s*=", re.IGNORECASE)),
    ("x-api-key header", re.compile(r"\bx-api-key\s*[:=]", re.IGNORECASE)),
    ("webhook key parameter", re.compile(r"[?&]key\s*=", re.IGNORECASE)),
    ("secret parameter", re.compile(r"\bsecret\s*=", re.IGNORECASE)),
    ("token parameter", re.compile(r"\btoken\s*=", re.IGNORECASE)),
    ("password parameter", re.compile(r"\bpassword\s*=", re.IGNORECASE)),
)


@dataclass(frozen=True)
class FinalizeIssue:
    scope: str
    message: str
    value: str = ""


@dataclass(frozen=True)
class FinalizedArchive:
    archive_dir: Path
    validation_file: Path
    manifest_file: Path
    manifest_json_file: Path
    seal_file: Path
    package_file: Path
    package_digest_file: Path


@dataclass(frozen=True)
class VerifiedArchive:
    archive_dir: Path
    manifest_file: Path
    manifest_json_file: Path
    package_file: Path
    package_digest_file: Path


@dataclass(frozen=True)
class VerifiedPackage:
    package_file: Path
    package_digest_file: Path
    archive_name: str


class FinalizeArchiveError(Exception):
    def __init__(self, issues: list[FinalizeIssue]) -> None:
        super().__init__("ops drill archive finalization failed")
        self.issues = issues


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


def _archive_validator() -> ModuleType:
    return _load_module(
        "validate_ops_drill_archive",
        _script_dir() / "validate_ops_drill_archive.py",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scan_file(path: Path, root: Path) -> list[FinalizeIssue]:
    return _scan_text(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8", errors="ignore"))


def _scan_text(scope: str, text: str) -> list[FinalizeIssue]:
    issues: list[FinalizeIssue] = []
    for label, pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            issues.append(
                FinalizeIssue(
                    scope,
                    f"contains sensitive URL/token evidence: {label}",
                    pattern.pattern,
                )
            )
    return issues


def _sensitive_scan_files(archive_dir: Path) -> list[Path]:
    files: list[Path] = []
    for child in (Path("raw"), Path("completed")):
        scan_dir = archive_dir / child
        if scan_dir.is_dir():
            files.extend(sorted(item for item in scan_dir.rglob("*") if item.is_file()))
    for rel_path in (Path("README.md"), Path(VALIDATION)):
        path = archive_dir / rel_path
        if path.is_file():
            files.append(path)
    return files


def scan_sensitive_evidence(archive_dir: Path) -> list[FinalizeIssue]:
    issues: list[FinalizeIssue] = []
    for child in (Path("raw"), Path("completed")):
        scan_dir = archive_dir / child
        if not scan_dir.exists():
            issues.append(FinalizeIssue(child.as_posix(), "required archive directory is missing"))
            continue
        if not scan_dir.is_dir():
            issues.append(FinalizeIssue(child.as_posix(), "archive path must be a directory"))
            continue
    if issues:
        return issues

    for path in _sensitive_scan_files(archive_dir):
        issues.extend(_scan_file(path, archive_dir))
    return issues


def _required_file_issues(archive_dir: Path) -> list[FinalizeIssue]:
    issues: list[FinalizeIssue] = []
    if not archive_dir.exists():
        return [FinalizeIssue("archive", "archive directory does not exist", str(archive_dir))]
    if not archive_dir.is_dir():
        return [FinalizeIssue("archive", "archive path must be a directory", str(archive_dir))]
    if (archive_dir / SEAL_MARKER).exists():
        return [FinalizeIssue(SEAL_MARKER, "archive is already sealed; create a new archive for changes")]

    issues.extend(_unexpected_root_entry_issues(archive_dir))
    for rel_path in (Path("completed") / CI_RECORD, Path("completed") / ALERT_RECORD, Path("README.md")):
        path = archive_dir / rel_path
        if not path.is_file():
            issues.append(FinalizeIssue(rel_path.as_posix(), "required archive file is missing"))
    return issues


def _unexpected_root_entry_issues(archive_dir: Path) -> list[FinalizeIssue]:
    issues: list[FinalizeIssue] = []
    for path in sorted(archive_dir.iterdir()):
        if path.name not in ALLOWED_ROOT_ENTRIES:
            issues.append(
                FinalizeIssue(
                    path.name,
                    "unexpected file or directory in archive root; keep evidence under raw/ or completed/",
                )
            )
    return issues


def _validator_ok_output(completed_dir: Path) -> str:
    return f"OK: {completed_dir} contains completed passing ops drill records."


def validate_completed_records(archive_dir: Path) -> tuple[list[FinalizeIssue], str]:
    completed_dir = archive_dir / "completed"
    validator = _archive_validator()
    archive_issues = validator.validate_archive(completed_dir)
    issues = [
        FinalizeIssue(
            f"completed/{issue.scope}",
            issue.message,
            issue.value,
        )
        for issue in archive_issues
    ]
    return issues, _validator_ok_output(completed_dir)


def _validation_text(validation_output: str, finalized_at: str) -> str:
    return "\n".join(
        [
            f"Finalized at (UTC): {finalized_at}",
            "",
            "Validator output:",
            validation_output,
            "",
        ]
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_content_files(archive_dir: Path) -> list[Path]:
    rel_paths: list[Path] = []
    for child in (Path("raw"), Path("completed")):
        scan_dir = archive_dir / child
        if scan_dir.is_dir():
            rel_paths.extend(
                path.relative_to(archive_dir)
                for path in sorted(item for item in scan_dir.rglob("*") if item.is_file())
            )
    for rel_path in ROOT_CONTENT_FILES:
        if (archive_dir / rel_path).is_file():
            rel_paths.append(rel_path)
    return rel_paths


def _manifest_hash_files(archive_dir: Path) -> list[Path]:
    rel_paths = _archive_content_files(archive_dir)
    manifest_json = Path(MANIFEST_JSON)
    if (archive_dir / manifest_json).is_file():
        rel_paths.append(manifest_json)
    return rel_paths


def _file_entry(archive_dir: Path, rel_path: Path) -> dict[str, object]:
    path = archive_dir / rel_path
    return {
        "path": rel_path.as_posix(),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _read_readme_metadata(archive_dir: Path) -> dict[str, str]:
    metadata = {
        "archive_name": archive_dir.name,
        "environment": "",
        "app_version": "",
    }
    readme = archive_dir / "README.md"
    if not readme.is_file():
        return metadata

    for line in readme.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("- Environment:"):
            metadata["environment"] = line.split(":", 1)[1].strip()
        elif line.startswith("- APP_VERSION:"):
            metadata["app_version"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Archive:"):
            metadata["archive_name"] = line.split(":", 1)[1].strip()
    return metadata


def write_manifest_json(archive_dir: Path, finalized_at: str) -> Path:
    manifest_json_file = archive_dir / MANIFEST_JSON
    archive_metadata = _read_readme_metadata(archive_dir)
    manifest = {
        "schema_version": 1,
        "finalized_at_utc": finalized_at,
        "generator": "scripts/ops/finalize_ops_drill_archive.py",
        "archive": {
            **archive_metadata,
            "repository": os.getenv("GITHUB_REPOSITORY", ""),
            "commit_sha": os.getenv("GITHUB_SHA", ""),
            "finalized_by": os.getenv("GITHUB_ACTOR") or os.getenv("USERNAME") or os.getenv("USER") or "",
        },
        "validation": {
            "path": VALIDATION,
            "sha256": _sha256(archive_dir / VALIDATION),
        },
        "records": {
            "ci": f"completed/{CI_RECORD}",
            "alert": f"completed/{ALERT_RECORD}",
        },
        "files": [_file_entry(archive_dir, rel_path) for rel_path in _archive_content_files(archive_dir)],
    }
    manifest_json_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_json_file


def write_manifest(archive_dir: Path) -> Path:
    manifest_file = archive_dir / MANIFEST
    lines: list[str] = []
    for rel_path in _manifest_hash_files(archive_dir):
        path = archive_dir / rel_path
        if not path.is_file():
            raise FileNotFoundError(f"manifest source file is missing: {rel_path.as_posix()}")
        lines.append(f"{_sha256(path)}  {rel_path.as_posix()}")
    manifest_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_file


def _read_manifest_sha256(archive_dir: Path) -> tuple[dict[str, str], list[FinalizeIssue]]:
    manifest_file = archive_dir / MANIFEST
    if not manifest_file.is_file():
        return {}, [FinalizeIssue(MANIFEST, "manifest file is missing")]

    return _parse_manifest_sha256_text(manifest_file.read_text(encoding="utf-8"))


def _parse_manifest_sha256_text(text: str) -> tuple[dict[str, str], list[FinalizeIssue]]:
    entries: dict[str, str] = {}
    issues: list[FinalizeIssue] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if "  " not in line:
            issues.append(FinalizeIssue(MANIFEST, f"line {line_number} is not in '<sha256>  <path>' format", raw_line))
            continue
        digest, rel_path = line.split("  ", 1)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            issues.append(FinalizeIssue(MANIFEST, f"line {line_number} has an invalid sha256 digest", digest))
            continue
        if rel_path in entries:
            issues.append(FinalizeIssue(MANIFEST, f"duplicate manifest entry: {rel_path}"))
            continue
        entries[rel_path] = digest
    return entries, issues


def _verify_manifest_sha256(archive_dir: Path) -> list[FinalizeIssue]:
    entries, issues = _read_manifest_sha256(archive_dir)
    if issues:
        return issues

    expected_paths = {rel_path.as_posix() for rel_path in _manifest_hash_files(archive_dir)}
    actual_paths = set(entries)
    missing = sorted(expected_paths - actual_paths)
    unexpected = sorted(actual_paths - expected_paths)
    issues.extend(FinalizeIssue(MANIFEST, "manifest is missing expected file", path) for path in missing)
    issues.extend(FinalizeIssue(MANIFEST, "manifest contains unexpected file", path) for path in unexpected)

    for rel_path, expected_digest in entries.items():
        path = archive_dir / rel_path
        if not path.is_file():
            issues.append(FinalizeIssue(MANIFEST, "manifest entry file is missing", rel_path))
            continue
        actual_digest = _sha256(path)
        if actual_digest != expected_digest:
            issues.append(
                FinalizeIssue(
                    rel_path,
                    "sha256 does not match manifest.sha256",
                    f"expected={expected_digest} actual={actual_digest}",
                )
            )
    return issues


def _verify_manifest_json(archive_dir: Path) -> list[FinalizeIssue]:
    manifest_json_file = archive_dir / MANIFEST_JSON
    if not manifest_json_file.is_file():
        return [FinalizeIssue(MANIFEST_JSON, "manifest json file is missing")]

    try:
        manifest = json.loads(manifest_json_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [FinalizeIssue(MANIFEST_JSON, "manifest json is invalid", str(exc))]

    issues: list[FinalizeIssue] = []
    if manifest.get("schema_version") != 1:
        issues.append(FinalizeIssue(MANIFEST_JSON, "unsupported schema_version", str(manifest.get("schema_version"))))

    archive = manifest.get("archive")
    if not isinstance(archive, dict) or archive.get("archive_name") != archive_dir.name:
        issues.append(FinalizeIssue(MANIFEST_JSON, "archive name does not match directory", archive_dir.name))

    finalized_at = manifest.get("finalized_at_utc")
    if not isinstance(finalized_at, str) or not re.fullmatch(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ", finalized_at):
        issues.append(FinalizeIssue(MANIFEST_JSON, "finalized_at_utc must be an ISO UTC timestamp", str(finalized_at)))

    records = manifest.get("records")
    if records != {"ci": f"completed/{CI_RECORD}", "alert": f"completed/{ALERT_RECORD}"}:
        issues.append(FinalizeIssue(MANIFEST_JSON, "records mapping is invalid", str(records)))

    validation = manifest.get("validation")
    if not isinstance(validation, dict) or validation.get("sha256") != _sha256(archive_dir / VALIDATION):
        issues.append(FinalizeIssue(MANIFEST_JSON, "validation hash does not match validation.txt"))

    files = manifest.get("files")
    if not isinstance(files, list):
        return issues + [FinalizeIssue(MANIFEST_JSON, "files must be a list")]

    expected_paths = {rel_path.as_posix() for rel_path in _archive_content_files(archive_dir)}
    seen_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            issues.append(FinalizeIssue(MANIFEST_JSON, "file entry must be an object", str(entry)))
            continue
        rel_path = str(entry.get("path", ""))
        if not rel_path:
            issues.append(FinalizeIssue(MANIFEST_JSON, "file entry path is missing", str(entry)))
            continue
        if rel_path in seen_paths:
            issues.append(FinalizeIssue(MANIFEST_JSON, "duplicate file entry", rel_path))
            continue
        seen_paths.add(rel_path)
        path = archive_dir / rel_path
        if not path.is_file():
            issues.append(FinalizeIssue(MANIFEST_JSON, "file entry is missing from archive", rel_path))
            continue
        expected_digest = _sha256(path)
        expected_size = path.stat().st_size
        if entry.get("sha256") != expected_digest:
            issues.append(FinalizeIssue(rel_path, "sha256 does not match manifest.json", str(entry.get("sha256"))))
        if entry.get("bytes") != expected_size:
            issues.append(FinalizeIssue(rel_path, "byte size does not match manifest.json", str(entry.get("bytes"))))

    missing = sorted(expected_paths - seen_paths)
    unexpected = sorted(seen_paths - expected_paths)
    issues.extend(FinalizeIssue(MANIFEST_JSON, "manifest json is missing expected file", path) for path in missing)
    issues.extend(FinalizeIssue(MANIFEST_JSON, "manifest json contains unexpected file", path) for path in unexpected)
    return issues


def write_seal_marker(archive_dir: Path, finalized_at: str) -> Path:
    seal_file = archive_dir / SEAL_MARKER
    seal_file.write_text(
        "\n".join(
            [
                f"sealed_at_utc={finalized_at}",
                "sealed_by=scripts/ops/finalize_ops_drill_archive.py",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return seal_file


def package_archive(archive_dir: Path) -> tuple[Path, Path]:
    package_file = archive_dir.parent / f"{archive_dir.name}.zip"
    digest_file = archive_dir.parent / f"{archive_dir.name}.zip.sha256"
    with zipfile.ZipFile(package_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel_path in _package_archive_files(archive_dir):
            archive.write(archive_dir / rel_path, (Path(archive_dir.name) / rel_path).as_posix())
    digest_file.write_text(f"{_sha256(package_file)}  {package_file.name}\n", encoding="utf-8")
    return package_file, digest_file


def _package_archive_files(archive_dir: Path) -> list[Path]:
    return [*_manifest_hash_files(archive_dir), Path(MANIFEST)]


def _package_paths(archive_dir: Path) -> tuple[Path, Path]:
    package_file = archive_dir.parent / f"{archive_dir.name}.zip"
    digest_file = archive_dir.parent / f"{archive_dir.name}.zip.sha256"
    return package_file, digest_file


def _package_digest_path(package_file: Path) -> Path:
    return Path(f"{package_file}.sha256")


def _read_zip_sidecar(package_file: Path) -> tuple[str, list[FinalizeIssue]]:
    digest_file = _package_digest_path(package_file)
    if not digest_file.is_file():
        return "", [FinalizeIssue(digest_file.name, "zip package sha256 sidecar is missing")]

    actual_digest_line = digest_file.read_text(encoding="utf-8").strip()
    expected_digest_line = f"{_sha256(package_file)}  {package_file.name}"
    if actual_digest_line != expected_digest_line:
        return actual_digest_line, [
            FinalizeIssue(
                digest_file.name,
                "zip package sha256 sidecar does not match package",
                actual_digest_line,
            )
        ]
    return actual_digest_line, []


def _zip_package_root(archive: zipfile.ZipFile) -> tuple[str, list[FinalizeIssue]]:
    file_names = [name for name in archive.namelist() if not name.endswith("/")]
    issues: list[FinalizeIssue] = []
    if not file_names:
        return "", [FinalizeIssue("zip", "zip package is empty")]

    counts: dict[str, int] = {}
    for name in file_names:
        counts[name] = counts.get(name, 0) + 1
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        issues.extend(FinalizeIssue("zip", "zip package contains duplicate file entries", name) for name in duplicates)

    top_levels: set[str] = set()
    for name in file_names:
        normalized = name.replace("\\", "/")
        parts = PurePosixPath(normalized).parts
        if normalized != name or PurePosixPath(normalized).is_absolute() or ".." in parts:
            issues.append(FinalizeIssue("zip", "zip package contains unsafe path", name))
            continue
        if len(parts) < 2:
            issues.append(FinalizeIssue("zip", "zip package entry is missing archive root", name))
            continue
        top_levels.add(parts[0])

    if issues:
        return "", issues
    if len(top_levels) != 1:
        return "", [FinalizeIssue("zip", "zip package must contain exactly one archive root", ", ".join(sorted(top_levels)))]
    return next(iter(top_levels)), []


def _verify_package_manifest_json(
    archive: zipfile.ZipFile,
    root: str,
    manifest: dict[str, object],
    expected_content_paths: set[str],
) -> list[FinalizeIssue]:
    issues: list[FinalizeIssue] = []
    if manifest.get("schema_version") != 1:
        issues.append(FinalizeIssue(MANIFEST_JSON, "unsupported schema_version", str(manifest.get("schema_version"))))

    archive_block = manifest.get("archive")
    if not isinstance(archive_block, dict) or archive_block.get("archive_name") != root:
        issues.append(FinalizeIssue(MANIFEST_JSON, "archive name does not match zip root", root))

    files = manifest.get("files")
    if not isinstance(files, list):
        return issues + [FinalizeIssue(MANIFEST_JSON, "files must be a list")]

    seen_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            issues.append(FinalizeIssue(MANIFEST_JSON, "file entry must be an object", str(entry)))
            continue
        rel_path = str(entry.get("path", ""))
        if not rel_path:
            issues.append(FinalizeIssue(MANIFEST_JSON, "file entry path is missing", str(entry)))
            continue
        if rel_path in seen_paths:
            issues.append(FinalizeIssue(MANIFEST_JSON, "duplicate file entry", rel_path))
            continue
        seen_paths.add(rel_path)
        zip_name = f"{root}/{rel_path}"
        try:
            data = archive.read(zip_name)
        except KeyError:
            issues.append(FinalizeIssue(MANIFEST_JSON, "file entry is missing from zip", rel_path))
            continue
        if entry.get("sha256") != hashlib.sha256(data).hexdigest():
            issues.append(FinalizeIssue(rel_path, "sha256 does not match manifest.json", str(entry.get("sha256"))))
        if entry.get("bytes") != len(data):
            issues.append(FinalizeIssue(rel_path, "byte size does not match manifest.json", str(entry.get("bytes"))))

    missing = sorted(expected_content_paths - seen_paths)
    unexpected = sorted(seen_paths - expected_content_paths)
    issues.extend(FinalizeIssue(MANIFEST_JSON, "manifest json is missing expected file", path) for path in missing)
    issues.extend(FinalizeIssue(MANIFEST_JSON, "manifest json contains unexpected file", path) for path in unexpected)
    return issues


def verify_package_file(package_file: Path) -> VerifiedPackage:
    package_file = package_file.resolve()
    issues: list[FinalizeIssue] = []
    if not package_file.exists():
        raise FinalizeArchiveError([FinalizeIssue("package", "zip package does not exist", str(package_file))])
    if not package_file.is_file():
        raise FinalizeArchiveError([FinalizeIssue("package", "zip package path must be a file", str(package_file))])

    _, sidecar_issues = _read_zip_sidecar(package_file)
    issues.extend(sidecar_issues)
    if issues:
        raise FinalizeArchiveError(issues)

    try:
        with zipfile.ZipFile(package_file) as archive:
            root, root_issues = _zip_package_root(archive)
            issues.extend(root_issues)
            if issues:
                raise FinalizeArchiveError(issues)

            manifest_name = f"{root}/{MANIFEST}"
            manifest_json_name = f"{root}/{MANIFEST_JSON}"
            validation_name = f"{root}/{VALIDATION}"
            actual_file_names = {name for name in archive.namelist() if not name.endswith("/")}
            for required_name in (manifest_name, manifest_json_name, validation_name):
                if required_name not in actual_file_names:
                    issues.append(FinalizeIssue("zip", "zip package is missing required file", required_name))
            if issues:
                raise FinalizeArchiveError(issues)

            manifest_entries, manifest_issues = _parse_manifest_sha256_text(archive.read(manifest_name).decode("utf-8"))
            issues.extend(manifest_issues)
            if issues:
                raise FinalizeArchiveError(issues)

            required_manifest_entries = {
                f"raw/ci-deployment-drill-record/{CI_RECORD}",
                f"raw/alert-webhook-drill-record/{ALERT_RECORD}",
                f"completed/{CI_RECORD}",
                f"completed/{ALERT_RECORD}",
                "README.md",
                VALIDATION,
                SEAL_MARKER,
                MANIFEST_JSON,
            }
            missing_required = sorted(required_manifest_entries - set(manifest_entries))
            issues.extend(FinalizeIssue(MANIFEST, "manifest is missing required archive file", path) for path in missing_required)

            expected_file_names = {f"{root}/{rel_path}" for rel_path in manifest_entries} | {manifest_name}
            missing = sorted(expected_file_names - actual_file_names)
            unexpected = sorted(actual_file_names - expected_file_names)
            issues.extend(FinalizeIssue("zip", "zip package is missing expected file", path) for path in missing)
            issues.extend(FinalizeIssue("zip", "zip package contains unexpected file", path) for path in unexpected)
            if issues:
                raise FinalizeArchiveError(issues)

            manifest_data = json.loads(archive.read(manifest_json_name).decode("utf-8"))
            content_paths = set(manifest_entries) - {MANIFEST_JSON}
            issues.extend(_verify_package_manifest_json(archive, root, manifest_data, content_paths))
            if issues:
                raise FinalizeArchiveError(issues)

            validation_digest = hashlib.sha256(archive.read(validation_name)).hexdigest()
            validation_block = manifest_data.get("validation")
            if not isinstance(validation_block, dict) or validation_block.get("sha256") != validation_digest:
                issues.append(FinalizeIssue(MANIFEST_JSON, "validation hash does not match zip validation.txt"))
                raise FinalizeArchiveError(issues)

            for rel_path, expected_digest in manifest_entries.items():
                zip_name = f"{root}/{rel_path}"
                data = archive.read(zip_name)
                actual_digest = hashlib.sha256(data).hexdigest()
                if actual_digest != expected_digest:
                    issues.append(
                        FinalizeIssue(
                            rel_path,
                            "sha256 does not match manifest.sha256",
                            f"expected={expected_digest} actual={actual_digest}",
                        )
                    )
                if rel_path.startswith(("raw/", "completed/")) or rel_path in {"README.md", VALIDATION}:
                    issues.extend(_scan_text(rel_path, data.decode("utf-8", errors="ignore")))
            if issues:
                raise FinalizeArchiveError(issues)

    except zipfile.BadZipFile as exc:
        raise FinalizeArchiveError([FinalizeIssue(package_file.name, "zip package is invalid", str(exc))]) from exc
    except json.JSONDecodeError as exc:
        raise FinalizeArchiveError([FinalizeIssue(MANIFEST_JSON, "manifest json is invalid", str(exc))]) from exc

    return VerifiedPackage(
        package_file=package_file,
        package_digest_file=_package_digest_path(package_file),
        archive_name=root,
    )


def _verify_package(archive_dir: Path) -> list[FinalizeIssue]:
    package_file, digest_file = _package_paths(archive_dir)
    issues: list[FinalizeIssue] = []
    try:
        verify_package_file(package_file)
    except FinalizeArchiveError as exc:
        issues.extend(exc.issues)
    if issues:
        return issues
    return []


def finalize_archive(archive_dir: Path) -> FinalizedArchive:
    archive_dir = archive_dir.resolve()
    issues = _required_file_issues(archive_dir)
    if not issues:
        issues.extend(scan_sensitive_evidence(archive_dir))
    if not issues:
        validation_issues, validation_output = validate_completed_records(archive_dir)
        issues.extend(validation_issues)
    else:
        validation_output = ""

    if issues:
        raise FinalizeArchiveError(issues)

    finalized_at = _utc_now()
    validation_file = archive_dir / VALIDATION
    previous_validation = validation_file.read_text(encoding="utf-8") if validation_file.exists() else None
    package_file, package_digest_file = _package_paths(archive_dir)
    generated_paths = (
        archive_dir / SEAL_MARKER,
        archive_dir / MANIFEST_JSON,
        archive_dir / MANIFEST,
        package_file,
        package_digest_file,
    )
    try:
        validation_file.write_text(_validation_text(validation_output, finalized_at), encoding="utf-8")
        seal_file = write_seal_marker(archive_dir, finalized_at)
        manifest_json_file = write_manifest_json(archive_dir, finalized_at)
        manifest_file = write_manifest(archive_dir)
        package_file, package_digest_file = package_archive(archive_dir)
    except Exception:
        for path in generated_paths:
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        if previous_validation is None:
            try:
                if validation_file.exists():
                    validation_file.unlink()
            except OSError:
                pass
        else:
            validation_file.write_text(previous_validation, encoding="utf-8")
        raise
    return FinalizedArchive(
        archive_dir=archive_dir,
        validation_file=validation_file,
        manifest_file=manifest_file,
        manifest_json_file=manifest_json_file,
        seal_file=seal_file,
        package_file=package_file,
        package_digest_file=package_digest_file,
    )


def verify_finalized_archive(archive_dir: Path) -> VerifiedArchive:
    archive_dir = archive_dir.resolve()
    issues: list[FinalizeIssue] = []
    if not archive_dir.exists():
        raise FinalizeArchiveError([FinalizeIssue("archive", "archive directory does not exist", str(archive_dir))])
    if not archive_dir.is_dir():
        raise FinalizeArchiveError([FinalizeIssue("archive", "archive path must be a directory", str(archive_dir))])

    issues.extend(_unexpected_root_entry_issues(archive_dir))
    for rel_path in (
        Path("completed") / CI_RECORD,
        Path("completed") / ALERT_RECORD,
        Path("README.md"),
        Path(VALIDATION),
        Path(MANIFEST_JSON),
        Path(MANIFEST),
        Path(SEAL_MARKER),
    ):
        if not (archive_dir / rel_path).is_file():
            issues.append(FinalizeIssue(rel_path.as_posix(), "required finalized archive file is missing"))

    if not issues:
        issues.extend(scan_sensitive_evidence(archive_dir))
    if not issues:
        validation_issues, _validation_output = validate_completed_records(archive_dir)
        issues.extend(validation_issues)
    if not issues:
        issues.extend(_verify_manifest_json(archive_dir))
        issues.extend(_verify_manifest_sha256(archive_dir))
        issues.extend(_verify_package(archive_dir))

    if issues:
        raise FinalizeArchiveError(issues)

    package_file, package_digest_file = _package_paths(archive_dir)
    return VerifiedArchive(
        archive_dir=archive_dir,
        manifest_file=archive_dir / MANIFEST,
        manifest_json_file=archive_dir / MANIFEST_JSON,
        package_file=package_file,
        package_digest_file=package_digest_file,
    )


def format_issues(issues: list[FinalizeIssue]) -> str:
    lines = ["Ops drill archive finalization failed:"]
    for issue in issues:
        suffix = f" (value: {issue.value})" if issue.value else ""
        lines.append(f"- {issue.scope}: {issue.message}{suffix}")
    return "\n".join(lines)


def _operation_mode(args: argparse.Namespace) -> str:
    if args.verify_package:
        return "verify-package"
    if args.verify:
        return "verify"
    return "finalize"


def _operation_label(mode: str) -> str:
    return {
        "finalize": "finalize archive",
        "verify": "verify archive",
        "verify-package": "verify package",
    }.get(mode, mode)


def _path_entry(path: Path) -> str:
    return str(path)


def _issue_entry(issue: FinalizeIssue) -> dict[str, str]:
    return {
        "scope": issue.scope,
        "message": issue.message,
        "value": issue.value,
    }


def _base_summary(mode: str, status: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at_utc": _utc_now(),
        "mode": mode,
        "status": status,
    }


def _success_summary(mode: str, result: FinalizedArchive | VerifiedArchive | VerifiedPackage) -> dict[str, object]:
    payload = _base_summary(mode, "ok")
    if isinstance(result, FinalizedArchive):
        payload["archive_name"] = result.archive_dir.name
        payload["paths"] = {
            "archive_dir": _path_entry(result.archive_dir),
            "validation": _path_entry(result.validation_file),
            "manifest": _path_entry(result.manifest_file),
            "manifest_json": _path_entry(result.manifest_json_file),
            "seal": _path_entry(result.seal_file),
            "package": _path_entry(result.package_file),
            "package_sha256": _path_entry(result.package_digest_file),
        }
    elif isinstance(result, VerifiedArchive):
        payload["archive_name"] = result.archive_dir.name
        payload["paths"] = {
            "archive_dir": _path_entry(result.archive_dir),
            "manifest": _path_entry(result.manifest_file),
            "manifest_json": _path_entry(result.manifest_json_file),
            "package": _path_entry(result.package_file),
            "package_sha256": _path_entry(result.package_digest_file),
        }
    else:
        payload["archive_name"] = result.archive_name
        payload["paths"] = {
            "package": _path_entry(result.package_file),
            "package_sha256": _path_entry(result.package_digest_file),
        }
    return payload


def _failure_summary(mode: str, issues: list[FinalizeIssue]) -> dict[str, object]:
    payload = _base_summary(mode, "failed")
    payload["issue_count"] = len(issues)
    payload["issues"] = [_issue_entry(issue) for issue in issues]
    return payload


def _error_summary(mode: str, error: Exception) -> dict[str, object]:
    payload = _base_summary(mode, "error")
    payload["error"] = str(error)
    return payload


def write_summary_json(destination: str | None, payload: dict[str, object]) -> Path | None:
    if not destination:
        return None
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Finalize a prepared operations drill archive after completed records are filled."
    )
    parser.add_argument("archive_dir", nargs="?", help="Archive root created by prepare_ops_drill_archive.py.")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify an already finalized archive without rewriting files.",
    )
    parser.add_argument(
        "--verify-package",
        help="Verify a finalized zip package and its sidecar without requiring an extracted archive directory.",
    )
    parser.add_argument(
        "--summary-json",
        help="Write a machine-readable JSON summary for CI/release logs.",
    )
    args = parser.parse_args(argv)
    if args.verify_package and args.archive_dir:
        parser.error("pass either archive_dir or --verify-package, not both")
    if not args.verify_package and not args.archive_dir:
        parser.error("archive_dir is required unless --verify-package is used")
    if args.verify and args.verify_package:
        parser.error("--verify cannot be combined with --verify-package")
    if args.summary_json:
        summary_path = Path(args.summary_json).resolve()
        if args.archive_dir:
            archive_dir = Path(args.archive_dir).resolve()
            package_file, package_digest_file = _package_paths(archive_dir)
            package_file = package_file.resolve()
            package_digest_file = package_digest_file.resolve()
            if summary_path == archive_dir or archive_dir in summary_path.parents:
                parser.error("--summary-json must be outside the archive directory")
            if summary_path == package_file or summary_path == package_digest_file:
                parser.error("--summary-json must not overwrite the archive package or digest sidecar")
        if args.verify_package:
            package_file = Path(args.verify_package).resolve()
            package_digest_file = _package_digest_path(package_file).resolve()
            if summary_path == package_file or summary_path == package_digest_file:
                parser.error("--summary-json must not overwrite the package or digest sidecar")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    mode = _operation_mode(args)
    try:
        if args.verify_package:
            verified_package = verify_package_file(Path(args.verify_package))
            write_summary_json(args.summary_json, _success_summary(mode, verified_package))
            print(f"OK: verified finalized ops drill package: {verified_package.package_file}")
            print(f"Package SHA256: {verified_package.package_digest_file}")
            print(f"Archive root: {verified_package.archive_name}")
            return 0
        if args.verify:
            verified = verify_finalized_archive(Path(args.archive_dir))
            write_summary_json(args.summary_json, _success_summary(mode, verified))
            print(f"OK: verified finalized ops drill archive: {verified.archive_dir}")
            print(f"Manifest: {verified.manifest_file}")
            print(f"Manifest JSON: {verified.manifest_json_file}")
            print(f"Package: {verified.package_file}")
            print(f"Package SHA256: {verified.package_digest_file}")
            return 0
        finalized = finalize_archive(Path(args.archive_dir))
        write_summary_json(args.summary_json, _success_summary(mode, finalized))
    except FinalizeArchiveError as exc:
        try:
            write_summary_json(args.summary_json, _failure_summary(mode, exc.issues))
        except OSError as summary_exc:
            print(format_issues(exc.issues), file=sys.stderr)
            print(f"ERROR: cannot write summary json: {summary_exc}", file=sys.stderr)
            return 2
        print(format_issues(exc.issues), file=sys.stderr)
        return 1
    except (OSError, RuntimeError) as exc:
        try:
            write_summary_json(args.summary_json, _error_summary(mode, exc))
        except OSError as summary_exc:
            print(f"ERROR: cannot write summary json: {summary_exc}", file=sys.stderr)
        print(f"ERROR: cannot {_operation_label(mode)}: {exc}", file=sys.stderr)
        return 2

    print(f"OK: finalized ops drill archive: {finalized.archive_dir}")
    print(f"Validation: {finalized.validation_file}")
    print(f"Manifest: {finalized.manifest_file}")
    print(f"Manifest JSON: {finalized.manifest_json_file}")
    print(f"Seal: {finalized.seal_file}")
    print(f"Package: {finalized.package_file}")
    print(f"Package SHA256: {finalized.package_digest_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
