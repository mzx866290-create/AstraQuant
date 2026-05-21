"""全市场行情快照批量采集（腾讯接口）"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from sqlalchemy import text

from backend.shared.database import SessionLocal, engine
from backend.shared.models import (
    DailySnapshot,
    IndustryDailySnapshot,
    IndustryHealthScore,
    PipelineRunLog,
    RejectionLog,
    Stock,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 80
CONCURRENCY = 10
TENCENT_URL = "https://qt.gtimg.cn/q="


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 3650) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, min_value), max_value)


def _tencent_code(symbol: str) -> str:
    code = symbol[:6]
    text = (symbol or "").upper()
    if text.endswith(".BJ") or code.startswith(("4", "8", "920")):
        prefix = "bj"
    else:
        prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    return f"{prefix}{code}"


def _parse_tencent_line(line: str) -> Optional[dict]:
    match = re.search(r'v_(\w+)="(.*)"', line)
    if not match:
        return None
    raw_code = match.group(1)
    parts = match.group(2).split("~")
    if len(parts) < 47:
        return None

    def f(idx: int) -> float:
        try:
            return float(parts[idx])
        except (IndexError, TypeError, ValueError):
            return 0.0

    price = f(3)
    if price <= 0:
        return None

    market_prefix = raw_code[:2]
    code_digits = raw_code[2:]
    suffix = "SH" if market_prefix == "sh" else "BJ" if market_prefix == "bj" else "SZ"
    symbol = f"{code_digits}.{suffix}"

    return {
        "symbol": symbol,
        "name": parts[1] if len(parts) > 1 else "",
        "market": suffix,
        "open": f(5),
        "high": f(33),
        "low": f(34),
        "close": price,
        "prev_close": f(4),
        "change_pct": f(32),
        "volume": f(36) * 100,
        "turnover": f(37) * 10000,
        "turnover_rate": f(38),
        "total_mv": f(44) * 1e8,
        "circ_mv": f(45) * 1e8,
    }


def _fetch_batch_sync(symbols: list[str]) -> list[dict]:
    codes = ",".join(_tencent_code(s) for s in symbols)
    try:
        resp = requests.get(
            TENCENT_URL + codes,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
        resp.encoding = "gbk"
    except Exception as e:
        logger.warning(f"Tencent batch request failed: {e}")
        return []

    results = []
    for line in resp.text.strip().split("\n"):
        parsed = _parse_tencent_line(line.strip())
        if parsed:
            results.append(parsed)
    return results


def _fetch_fallback_sync(symbols: list[str]) -> list[dict]:
    try:
        from backend.services.data_crawler.sources.sina_tencent_source import SinaTencentSource

        source = SinaTencentSource()
    except Exception as exc:
        logger.warning("fallback quote source unavailable: %s", exc)
        return []

    results: list[dict] = []
    for symbol in symbols:
        try:
            quote = source._fetch_realtime_quote_sync(symbol)
            price = float(quote.get("price") or quote.get("close") or 0)
            if price <= 0:
                continue
            resolved = quote.get("symbol") or symbol
            market = "BJ" if resolved.endswith(".BJ") else "SH" if resolved.endswith(".SH") else "SZ"
            results.append({
                "symbol": resolved,
                "name": quote.get("name", ""),
                "market": market,
                "open": float(quote.get("open") or price),
                "high": float(quote.get("high") or price),
                "low": float(quote.get("low") or price),
                "close": price,
                "prev_close": float(quote.get("prev_close") or 0),
                "change_pct": float(quote.get("change_pct") or 0),
                "volume": float(quote.get("volume") or 0),
                "turnover": float(quote.get("turnover") or 0),
                "turnover_rate": float(quote.get("turnover_rate") or 0),
                "total_mv": float(quote.get("total_mv") or 0),
                "circ_mv": float(quote.get("circ_mv") or 0),
                "source": "sina-tencent",
            })
        except Exception as exc:
            logger.debug("fallback quote failed for %s: %s", symbol, exc)
    return results


async def _fetch_batch_async(symbols: list[str]) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_batch_sync, symbols)


async def _fetch_fallback_async(symbols: list[str]) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_fallback_sync, symbols)


def _load_all_symbols() -> list[str]:
    db = SessionLocal()
    try:
        rows = db.query(Stock.symbol).filter(Stock.is_active == True).all()
        return [r[0] for r in rows]
    finally:
        db.close()


def _compute_moving_averages(db, symbol: str, trade_date: str, close: float) -> dict:
    """从历史快照计算 MA5/MA20/MA60 和 vol_ratio_5d"""
    stmt = text(
        "SELECT close, volume FROM daily_snapshots "
        "WHERE symbol = :symbol AND trade_date < :td "
        "ORDER BY trade_date DESC LIMIT 60"
    )
    rows = db.execute(stmt, {"symbol": symbol, "td": trade_date}).fetchall()

    closes = [close] + [r[0] for r in rows if r[0]]
    volumes = [None] + [r[1] for r in rows if r[1] is not None]

    def ma(data, n):
        if len(data) < n:
            return None
        return sum(data[:n]) / n

    result = {
        "ma5": ma(closes, 5),
        "ma20": ma(closes, 20),
        "ma60": ma(closes, 60),
        "vol_ratio_5d": None,
    }

    if len(volumes) >= 6 and volumes[0] is not None:
        avg_5 = sum(v for v in volumes[1:6] if v) / max(sum(1 for v in volumes[1:6] if v), 1)
        if avg_5 > 0:
            result["vol_ratio_5d"] = volumes[0] / avg_5

    return result


async def collect_market_snapshot(trade_date: Optional[str] = None) -> dict:
    """
    采集全市场行情快照，存入 daily_snapshots 表。
    返回 {"collected": int, "errors": int, "trade_date": str}
    """
    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    all_symbols = _load_all_symbols()
    if not all_symbols:
        logger.error("No active symbols found in stocks table")
        return {"collected": 0, "errors": 0, "trade_date": trade_date}

    logger.info(f"Starting market snapshot collection: {len(all_symbols)} symbols, date={trade_date}")

    batches = [all_symbols[i:i + BATCH_SIZE] for i in range(0, len(all_symbols), BATCH_SIZE)]
    all_quotes: list[dict] = []
    errors = 0

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def fetch_with_semaphore(batch):
        async with semaphore:
            return await _fetch_batch_async(batch)

    tasks = [fetch_with_semaphore(batch) for batch in batches]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            errors += 1
            logger.warning(f"Batch failed: {result}")
        else:
            all_quotes.extend(result)

    expected = set(all_symbols)
    fetched = {item.get("symbol") for item in all_quotes}
    missing_symbols = [symbol for symbol in all_symbols if symbol not in fetched]
    fallback_saved = 0
    min_coverage = _env_int("DAILY_POOL_MIN_QUOTE_COVERAGE_PCT", 85, min_value=1, max_value=100) / 100
    if expected and len(fetched) / len(expected) < min_coverage and missing_symbols:
        fallback_limit = _env_int("DAILY_POOL_FALLBACK_QUOTE_LIMIT", 800, min_value=0, max_value=6000)
        fallback_symbols = missing_symbols[:fallback_limit]
        if fallback_symbols:
            fallback_quotes = await _fetch_fallback_async(fallback_symbols)
            seen = {item.get("symbol") for item in all_quotes}
            for quote in fallback_quotes:
                if quote.get("symbol") in seen:
                    continue
                all_quotes.append(quote)
                seen.add(quote.get("symbol"))
            fallback_saved = len(fallback_quotes)
            logger.info("Fallback quote fill: %d/%d symbols", fallback_saved, len(fallback_symbols))

    logger.info(f"Fetched {len(all_quotes)} quotes, {errors} batch errors")

    db = SessionLocal()
    try:
        saved = 0
        batch_buffer = []
        for quote in all_quotes:
            if quote["volume"] <= 0:
                continue

            ma_data = _compute_moving_averages(db, quote["symbol"], trade_date, quote["close"])

            snapshot = {
                "trade_date": trade_date,
                "symbol": quote["symbol"],
                "name": quote["name"],
                "market": quote["market"],
                "open": quote["open"],
                "high": quote["high"],
                "low": quote["low"],
                "close": quote["close"],
                "prev_close": quote["prev_close"],
                "change_pct": quote["change_pct"],
                "volume": quote["volume"],
                "turnover": quote["turnover"],
                "turnover_rate": quote["turnover_rate"],
                "total_mv": quote["total_mv"],
                "circ_mv": quote["circ_mv"],
                "vol_ratio_5d": ma_data["vol_ratio_5d"],
                "ma5": ma_data["ma5"],
                "ma20": ma_data["ma20"],
                "ma60": ma_data["ma60"],
                "source": quote.get("source") or "tencent",
                "created_at": datetime.now(timezone.utc),
            }
            batch_buffer.append(snapshot)

            if len(batch_buffer) >= 500:
                _upsert_batch(db, batch_buffer)
                saved += len(batch_buffer)
                batch_buffer = []

        if batch_buffer:
            _upsert_batch(db, batch_buffer)
            saved += len(batch_buffer)

        db.commit()
        logger.info(f"Saved {saved} snapshots for {trade_date}")
        return {
            "collected": saved,
            "errors": errors,
            "trade_date": trade_date,
            "expected": len(all_symbols),
            "coverage_pct": round((saved / len(all_symbols) * 100), 2) if all_symbols else 0,
            "fallback_quotes": fallback_saved,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save snapshots: {e}")
        raise
    finally:
        db.close()


def _upsert_batch(db, batch: list[dict]):
    """INSERT OR REPLACE batch of snapshots (SQLite compatible)."""
    for item in batch:
        existing = db.query(DailySnapshot).filter_by(
            trade_date=item["trade_date"], symbol=item["symbol"]
        ).first()
        if existing:
            for key, value in item.items():
                if key != "id":
                    setattr(existing, key, value)
        else:
            db.add(DailySnapshot(**item))


def cleanup_old_snapshots(keep_days: int = 90):
    """清理超过 keep_days 天的历史快照"""
    db = SessionLocal()
    try:
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        deleted = db.query(DailySnapshot).filter(DailySnapshot.trade_date < cutoff).delete()
        db.commit()
        logger.info(f"Cleaned up {deleted} old snapshots (before {cutoff})")
        return {"daily_snapshots": deleted, "cutoff": cutoff, "keep_days": keep_days}
    finally:
        db.close()


def cleanup_market_redundancy(
    *,
    daily_snapshot_days: int | None = None,
    industry_snapshot_days: int | None = None,
    industry_score_days: int | None = None,
    rejection_log_days: int | None = None,
    pipeline_log_days: int | None = None,
    clickhouse_minute_days: int | None = None,
    clickhouse_quote_days: int | None = None,
) -> dict:
    """Clean redundant quote/pipeline data with retention tuned by data value."""
    daily_days = daily_snapshot_days or _env_int("DAILY_POOL_DAILY_SNAPSHOT_KEEP_DAYS", 180, min_value=75)
    industry_days = industry_snapshot_days or _env_int("DAILY_POOL_INDUSTRY_SNAPSHOT_KEEP_DAYS", 180, min_value=75)
    score_days = industry_score_days or _env_int("DAILY_POOL_INDUSTRY_SCORE_KEEP_DAYS", 180, min_value=75)
    rejection_days = rejection_log_days or _env_int("DAILY_POOL_REJECTION_LOG_KEEP_DAYS", 120, min_value=30)
    pipeline_days = pipeline_log_days or _env_int("DAILY_POOL_RUN_LOG_KEEP_DAYS", 180, min_value=30)

    now = datetime.now()
    daily_cutoff = (now - timedelta(days=daily_days)).strftime("%Y-%m-%d")
    industry_cutoff = (now - timedelta(days=industry_days)).strftime("%Y-%m-%d")
    score_cutoff = (now - timedelta(days=score_days)).strftime("%Y-%m-%d")
    rejection_cutoff = (now - timedelta(days=rejection_days)).strftime("%Y-%m-%d")
    pipeline_cutoff = (now - timedelta(days=pipeline_days)).strftime("%Y-%m-%d")

    db = SessionLocal()
    try:
        deleted = {
            "daily_snapshots": db.query(DailySnapshot).filter(DailySnapshot.trade_date < daily_cutoff).delete(),
            "industry_daily_snapshots": db.query(IndustryDailySnapshot).filter(IndustryDailySnapshot.trade_date < industry_cutoff).delete(),
            "industry_health_scores": db.query(IndustryHealthScore).filter(IndustryHealthScore.trade_date < score_cutoff).delete(),
            "rejection_logs": db.query(RejectionLog).filter(RejectionLog.trade_date < rejection_cutoff).delete(),
            "pipeline_run_logs": db.query(PipelineRunLog).filter(PipelineRunLog.run_date < pipeline_cutoff).delete(),
        }
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    minute_days = clickhouse_minute_days or _env_int("CLICKHOUSE_STOCK_MINUTE_KEEP_DAYS", 14, min_value=1)
    quote_days = clickhouse_quote_days or _env_int("CLICKHOUSE_STOCK_QUOTES_KEEP_DAYS", 7, min_value=1)
    result = {
        "status": "ok",
        "deleted": deleted,
        "retention_days": {
            "daily_snapshots": daily_days,
            "industry_daily_snapshots": industry_days,
            "industry_health_scores": score_days,
            "rejection_logs": rejection_days,
            "pipeline_run_logs": pipeline_days,
            "clickhouse_stock_minute": minute_days,
            "clickhouse_stock_quotes": quote_days,
        },
        "cutoffs": {
            "daily_snapshots": daily_cutoff,
            "industry_daily_snapshots": industry_cutoff,
            "industry_health_scores": score_cutoff,
            "rejection_logs": rejection_cutoff,
            "pipeline_run_logs": pipeline_cutoff,
        },
    }

    if engine.dialect.name != "sqlite":
        result["clickhouse"] = _cleanup_clickhouse_runtime_rows(minute_days=minute_days, quote_days=quote_days)
    else:
        result["clickhouse"] = {"status": "skipped_sqlite"}

    logger.info("market redundancy cleanup result: %s", result)
    return result


def _cleanup_clickhouse_runtime_rows(*, minute_days: int, quote_days: int) -> dict:
    try:
        from backend.services.data_crawler.pipeline.etl import (
            ClickHouseWriteUnavailable,
            _clickhouse_table_name,
            _close_clickhouse_client,
            _create_clickhouse_client,
        )
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}

    try:
        minute_table = _clickhouse_table_name("CLICKHOUSE_STOCK_MINUTE_TABLE", "stock_minute")
        quote_table = _clickhouse_table_name("CLICKHOUSE_STOCK_QUOTES_TABLE", "stock_quotes")
    except ClickHouseWriteUnavailable as exc:
        return {"status": "invalid_table", "error": str(exc)}

    client = None
    try:
        client = _create_clickhouse_client()
        statements = [
            f"ALTER TABLE {minute_table} DELETE WHERE timestamp < now() - INTERVAL {minute_days} DAY SETTINGS mutations_sync = 1",
            f"ALTER TABLE {quote_table} DELETE WHERE updated_at < now() - INTERVAL {quote_days} DAY SETTINGS mutations_sync = 1",
        ]
        for statement in statements:
            client.execute(statement)
        return {"status": "ok", "statements": len(statements)}
    except Exception as exc:
        logger.warning("ClickHouse redundancy cleanup failed: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        if client is not None:
            _close_clickhouse_client(client)
