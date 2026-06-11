#!/usr/bin/env python
"""Run the observation-pool data-foundation health check + execution simulation
against the REAL database (whatever DATABASE_URL / USE_SQLITE resolves to).

Unlike review_smoke.py (which mocks the DB), this connects to the live data so
you can see the actual numbers before trusting the metrics or merging/deploying.

Examples:
    python backend/scripts/pool_foundation_check.py
    python backend/scripts/pool_foundation_check.py --lookback-days 30 --strategy auto
    python backend/scripts/pool_foundation_check.py --strict   # CI gate
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services.analysis_service.engine.review_tracker import (
    build_data_foundation_health,
    build_pool_scorecard,
    build_pool_simulation,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run observation-pool foundation health + simulation against the real DB."
    )
    parser.add_argument("--lookback-days", type=int, default=90, help="Lookback window in days (default 90)")
    parser.add_argument("--strategy", default="auto", help="Strategy id, or 'auto' for all (default auto)")
    parser.add_argument("--skip-scorecard", action="store_true", help="Skip the async scorecard (avoids kline fetch)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if tables are missing, data is insufficient, or the foundation is degraded.",
    )
    parser.add_argument(
        "--min-reproducible-rate",
        type=float,
        default=None,
        help="Exit non-zero if review price reproducibility falls below this rate (0-1).",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict:
    health = build_data_foundation_health(lookback_days=args.lookback_days)
    simulation = build_pool_simulation(lookback_days=args.lookback_days, strategy=args.strategy)
    result = {
        "lookback_days": args.lookback_days,
        "strategy": args.strategy,
        "data_foundation_health": health,
        "pool_simulation": simulation,
    }
    if not args.skip_scorecard:
        try:
            result["pool_scorecard"] = await build_pool_scorecard(
                lookback_days=args.lookback_days, strategy=args.strategy
            )
        except Exception as exc:  # noqa: BLE001 - surface, don't crash the whole check
            result["pool_scorecard"] = {"status": "error", "error": str(exc)[:200]}
    return result


def _exit_code(result: dict, args: argparse.Namespace) -> int:
    health = result.get("data_foundation_health") or {}
    simulation = result.get("pool_simulation") or {}

    # Reproducibility gate is independent of --strict so it can be used alone.
    if args.min_reproducible_rate is not None:
        price_quality = (health.get("price_source_quality") or {})
        rate = price_quality.get("reproducible_rate")
        if rate is not None and float(rate) < args.min_reproducible_rate:
            return 5

    if not args.strict:
        return 0
    if health.get("status") == "tables_missing" or simulation.get("status") == "tables_missing":
        return 2
    if simulation.get("status") == "insufficient_data":
        return 3
    if health.get("status") == "degraded":
        return 4
    return 0


def main() -> int:
    args = _parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return _exit_code(result, args)


if __name__ == "__main__":
    raise SystemExit(main())
