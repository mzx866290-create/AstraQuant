#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
from datetime import date
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.analysis_service.engine.review_tracker import (
    build_review_readiness,
    build_review_report,
    run_pending_reviews,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run research observation reviews and print a summary.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Review date in YYYY-MM-DD format")
    parser.add_argument("--offsets", default="T+1,T+5,T+20", help="Comma-separated review offsets")
    parser.add_argument("--report-only", action="store_true", help="Only print aggregated review report")
    parser.add_argument(
        "--include-readiness",
        action="store_true",
        help="Print readiness after running reviews/report.",
    )
    parser.add_argument(
        "--strict-readiness",
        action="store_true",
        help="Exit non-zero if readiness reports missing tables, errors, or no saved observations.",
    )
    parser.add_argument(
        "--require-reviewed",
        action="store_true",
        help="Exit non-zero unless readiness reports at least one generated review.",
    )
    parser.add_argument(
        "--require-no-pending",
        action="store_true",
        help="Exit non-zero if readiness reports pending reviews for the selected offsets.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    review_date = date.fromisoformat(args.date)
    offsets = tuple(part.strip() for part in args.offsets.split(",") if part.strip())

    if not args.report_only:
        result = await run_pending_reviews(review_date, offsets=offsets)
        print(json.dumps({"run_pending_reviews": result}, ensure_ascii=False, indent=2))

    report = build_review_report()
    print(json.dumps({"review_report": report}, ensure_ascii=False, indent=2))

    if args.include_readiness or args.strict_readiness or args.require_reviewed or args.require_no_pending:
        readiness = build_review_readiness(review_date=review_date, offsets=offsets)
        print(json.dumps({"review_readiness": readiness}, ensure_ascii=False, indent=2))
        if (args.strict_readiness or args.require_reviewed or args.require_no_pending) and readiness.get("status") in {
            "tables_missing",
            "error",
            "no_observations",
        }:
            return 2
        if args.require_reviewed and int((readiness.get("summary") or {}).get("reviews") or 0) <= 0:
            return 3
        if args.require_no_pending and int((readiness.get("summary") or {}).get("pending_reviews") or 0) > 0:
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
