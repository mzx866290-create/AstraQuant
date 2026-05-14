"""全市场行情快照批量采集（腾讯接口）"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import requests
from sqlalchemy import text

from backend.shared.database import SessionLocal
from backend.shared.models import DailySnapshot, Stock

logger = logging.getLogger(__name__)

BATCH_SIZE = 80
CONCURRENCY = 10
TENCENT_URL = "https://qt.gtimg.cn/q="


def _tencent_code(symbol: str) -> str:
    code = symbol[:6]
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
    suffix = "SH" if market_prefix == "sh" else "SZ"
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


async def _fetch_batch_async(symbols: list[str]) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_batch_sync, symbols)


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
                "source": "tencent",
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
        return {"collected": saved, "errors": errors, "trade_date": trade_date}
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


def cleanup_old_snapshots(keep_days: int = 30):
    """清理超过 keep_days 天的历史快照"""
    db = SessionLocal()
    try:
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        deleted = db.query(DailySnapshot).filter(DailySnapshot.trade_date < cutoff).delete()
        db.commit()
        logger.info(f"Cleaned up {deleted} old snapshots (before {cutoff})")
    finally:
        db.close()
