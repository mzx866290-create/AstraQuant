#!/usr/bin/env python
"""Synchronize SH/SZ A-share master data into the shared database."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def _fetch_rows(page_size: int, max_pages: int) -> tuple[list[dict], str]:
    from backend.services.data_crawler.sources.akshare_source import AKShareSource
    from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource
    from backend.services.data_crawler.sources.fallback_chain import DataSourceChain

    chain = DataSourceChain()
    chain.register_many(EastMoneySource(), AKShareSource())
    try:
        result = await chain.fetch_with_fallback(
            "fetch_stock_master",
            page_size=page_size,
            max_pages=max_pages,
            _timeout_seconds=90.0,
        )
        return result["data"], result["source"]
    finally:
        await chain.close()


def _sync_rows(rows: list[dict], deactivate_missing: bool) -> dict:
    from backend.services.data_crawler.pipeline.stock_master import StockMasterETL
    from backend.shared.database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        result = StockMasterETL().save(db, rows, deactivate_missing=deactivate_missing)
        return result.as_dict()
    finally:
        db.close()


async def main_async(args: argparse.Namespace) -> int:
    rows, source = await _fetch_rows(args.page_size, args.max_pages)
    payload = {
        "source": source,
        "fetched": len(rows),
        "dry_run": args.dry_run,
        "deactivate_missing": args.deactivate_missing,
    }
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if rows else 1

    payload.update(_sync_rows(rows, deactivate_missing=args.deactivate_missing))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("saved", 0) > 0 or payload.get("fetched", 0) > 0 else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-size", type=int, default=200, help="EastMoney page size, 50-500.")
    parser.add_argument("--max-pages", type=int, default=80, help="Maximum pages to fetch.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print summary without writing the database.")
    parser.add_argument(
        "--deactivate-missing",
        action="store_true",
        help="Mark existing DB stocks inactive when they are absent from the fetched stock master.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    os.chdir(ROOT)
    return asyncio.run(main_async(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
