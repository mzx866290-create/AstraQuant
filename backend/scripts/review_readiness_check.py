#!/usr/bin/env python
from __future__ import annotations

import argparse
from datetime import date
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services.analysis_service.engine.review_tracker import build_review_readiness


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check research review loop readiness.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Review date in YYYY-MM-DD format")
    parser.add_argument("--offsets", default="T+1,T+5,T+20", help="Comma-separated review offsets")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless observations exist and review tables are available.",
    )
    parser.add_argument(
        "--require-reviewed",
        action="store_true",
        help="Exit non-zero unless at least one review record exists for the selected environment.",
    )
    parser.add_argument(
        "--require-no-pending",
        action="store_true",
        help="Exit non-zero if selected offsets still have pending reviews.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    review_date = date.fromisoformat(args.date)
    offsets = tuple(part.strip() for part in args.offsets.split(",") if part.strip())
    result = build_review_readiness(review_date=review_date, offsets=offsets)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not args.strict and not args.require_reviewed and not args.require_no_pending:
        return 0
    if result.get("status") in {"tables_missing", "error", "no_observations"}:
        return 2
    if args.require_reviewed and int((result.get("summary") or {}).get("reviews") or 0) <= 0:
        return 3
    if args.require_no_pending and int((result.get("summary") or {}).get("pending_reviews") or 0) > 0:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
