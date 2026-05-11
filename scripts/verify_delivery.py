#!/usr/bin/env python
"""Run the local delivery verification checks.

This script intentionally uses the same commands we rely on during manual
handoff so a release candidate can be checked with one command.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "web"


def run_step(name: str, cmd: list[str], cwd: Path = ROOT) -> None:
    print(f"\n[verify] {name}")
    print(f"[cmd] {' '.join(cmd)}")
    started = time.perf_counter()
    result = subprocess.run(cmd, cwd=str(cwd), shell=False)
    elapsed = round(time.perf_counter() - started, 1)
    if result.returncode != 0:
        raise SystemExit(f"[fail] {name} failed after {elapsed}s")
    print(f"[ok] {name} ({elapsed}s)")


def main() -> int:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    python = sys.executable

    checks = [
        ("ops drill readiness preflight", [python, "scripts/ops/verify_ops_drill_readiness.py"], ROOT),
        ("secret hygiene gate", [python, "scripts/verify_secret_hygiene.py"], ROOT),
        ("backend compile", [python, "-m", "compileall", "backend", "scripts", "-q"], ROOT),
        ("backend unit tests", [python, "-m", "unittest", "discover", "backend/tests"], ROOT),
        ("backend coverage gate", [python, "scripts/verify_backend_coverage.py"], ROOT),
        ("AI analysis self-check", [python, "backend/scripts/ai_analysis_self_check.py"], ROOT),
        ("daily observation self-check", [python, "backend/scripts/daily_recommendations_self_check.py"], ROOT),
        ("research review smoke", [python, "backend/scripts/review_smoke.py"], ROOT),
        ("research review readiness check", [python, "backend/scripts/review_readiness_check.py"], ROOT),
        (
            "research review runner check",
            [python, "backend/scripts/review_tracker_run.py", "--report-only", "--include-readiness"],
            ROOT,
        ),
        ("frontend lint", [npm, "run", "lint"], FRONTEND),
        ("frontend type-check", [npm, "run", "type-check"], FRONTEND),
        ("frontend API compatibility", [npm, "run", "test:api-compat"], FRONTEND),
        ("frontend recommendations contract", [npm, "run", "test:recommendations-contract"], FRONTEND),
        ("frontend data quality contract", [npm, "run", "test:data-quality"], FRONTEND),
        ("frontend build", [npm, "run", "build"], FRONTEND),
        ("frontend smoke", [npm, "run", "smoke:frontend"], FRONTEND),
    ]

    for name, cmd, cwd in checks:
        run_step(name, cmd, cwd)

    print("\n[ok] delivery verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
