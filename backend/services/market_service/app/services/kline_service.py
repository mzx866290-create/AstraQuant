from __future__ import annotations

from datetime import date, datetime, timedelta
import math
import random
from typing import Optional


INTRADAY_PERIODS = {"1m", "5m", "15m", "30m", "60m"}
AGGREGATED_PERIODS = {"1w", "1M"}


async def load_kline_data(symbol: str, period: str, adjust: str, limit: int) -> tuple[list[dict], str]:
    kline_data: list[dict] = []
    source = "unavailable"

    if period in INTRADAY_PERIODS:
        return await fetch_eastmoney_period_kline(symbol, period, adjust, limit)

    if period == "1d":
        kline_data, source = await fetch_daily_kline(symbol, adjust)
    elif period in AGGREGATED_PERIODS:
        kline_data, source = await fetch_eastmoney_period_kline(symbol, period, adjust, limit)
        if not kline_data:
            daily_data, daily_source = await fetch_daily_kline(symbol, adjust)
            if daily_data:
                kline_data = aggregate_kline(daily_data, period)
                source = f"{daily_source}-aggregated"

    if not kline_data:
        local_limit = limit * 7 if period == "1w" else limit * 31 if period == "1M" else limit
        local_daily = await build_local_kline(symbol, min(local_limit, 2000))
        kline_data = aggregate_kline(local_daily, period) if period in AGGREGATED_PERIODS else local_daily
        source = "local-fallback"

    if len(kline_data) > limit:
        kline_data = kline_data[-limit:]

    return kline_data, source


def build_data_quality(source: str, period: str, kline_data: list[dict]) -> dict:
    warnings = []
    if source == "local-fallback":
        warnings.append("local fallback kline generated from local financial data; not exchange sourced")
    if source.endswith("-aggregated"):
        warnings.append(f"{period} kline aggregated from daily source because native period source was unavailable")
    if any(row.get("open") == 0 or row.get("high") == 0 or row.get("low") == 0 or row.get("close") == 0 for row in kline_data):
        warnings.append("one or more kline price fields are 0; source data may be incomplete")

    latest_date = kline_data[-1].get("date") if kline_data else None
    return data_quality(
        source=source,
        updated_at=str(latest_date) if latest_date else None,
        freshness="generated" if source == "local-fallback" else period,
        confidence=0.35 if source == "local-fallback" else 0.9,
        is_fallback=source == "local-fallback",
        warnings=warnings,
    )


def data_quality(
    source: str,
    updated_at: Optional[str] = None,
    freshness: str = "recent",
    confidence: float = 0.9,
    is_fallback: bool = False,
    warnings: Optional[list[str]] = None,
) -> dict:
    return {
        "source": source,
        "updated_at": updated_at or datetime.now().isoformat(),
        "freshness": freshness,
        "confidence": confidence,
        "is_fallback": is_fallback,
        "warnings": warnings or [],
    }


async def fetch_daily_kline(symbol: str, adjust: str) -> tuple[list[dict], str]:
    try:
        from backend.services.data_crawler.sources.sina_tencent_source import SinaTencentSource

        st = SinaTencentSource()
        data = await st.fetch_daily_kline(symbol)
        if data:
            return data, "sina-tencent"
    except Exception:
        pass

    data, source = await fetch_eastmoney_period_kline(symbol, "1d", adjust)
    if data:
        return data, source

    try:
        from backend.services.data_crawler.sources.akshare_source import AKShareSource

        ak = AKShareSource()
        data = await ak.fetch_daily_kline(symbol, adjust=adjust)
        if data:
            return data, "akshare"
    except Exception:
        pass
    return [], "unavailable"


async def fetch_eastmoney_period_kline(
    symbol: str,
    period: str,
    adjust: str,
    limit: int = 500,
) -> tuple[list[dict], str]:
    try:
        from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource

        em = EastMoneySource()
        try:
            data = await em.fetch_kline(symbol, period=period, adjust=adjust, limit=limit)
        finally:
            await em.close()
        if data:
            return data, "eastmoney"
    except Exception:
        pass
    return [], "eastmoney"


def aggregate_kline(rows: list[dict], period: str) -> list[dict]:
    if period == "1d":
        return rows

    grouped: dict[tuple[int, int], list[dict]] = {}
    for row in rows:
        row_date = parse_kline_date(row.get("date"))
        if not row_date:
            continue
        if period == "1w":
            iso = row_date.isocalendar()
            key = (iso.year, iso.week)
        else:
            key = (row_date.year, row_date.month)
        grouped.setdefault(key, []).append(row)

    result = []
    previous_close = None
    for key in sorted(grouped.keys()):
        items = sorted(grouped[key], key=lambda item: item.get("date", ""))
        if not items:
            continue
        open_price = safe_float(items[0].get("open"))
        close_price = safe_float(items[-1].get("close"))
        highs = [safe_float(item.get("high")) for item in items if safe_float(item.get("high")) is not None]
        lows = [safe_float(item.get("low")) for item in items if safe_float(item.get("low")) is not None]
        volumes = [safe_float(item.get("volume")) or 0 for item in items]
        turnovers = [safe_float(item.get("turnover")) or 0 for item in items]
        if open_price is None or close_price is None or not highs or not lows:
            continue
        change_pct = ((close_price - previous_close) / previous_close * 100) if previous_close else safe_float(items[-1].get("change_pct")) or 0
        first_date = parse_kline_date(items[0].get("date"))
        last_date = parse_kline_date(items[-1].get("date"))
        result.append({
            "date": last_date.isoformat() if last_date else str(items[-1].get("date")),
            "start_date": first_date.isoformat() if first_date else str(items[0].get("date")),
            "open": round(open_price, 2),
            "close": round(close_price, 2),
            "high": round(max(highs), 2),
            "low": round(min(lows), 2),
            "volume": int(sum(volumes)),
            "turnover": round(sum(turnovers), 2),
            "change_pct": round(change_pct, 2),
        })
        previous_close = close_price
    return result


def parse_kline_date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def safe_float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


async def build_local_kline(symbol: str, limit: int) -> list[dict]:
    code = symbol[:6]
    try:
        from backend.shared.database import SessionLocal
        from backend.shared.models import FinancialReport

        db = SessionLocal()
        try:
            report = (
                db.query(FinancialReport)
                .filter(FinancialReport.stock_symbol == code)
                .order_by(FinancialReport.report_date.desc())
                .first()
            )
            base_price = float(report.pb * report.bvps) if report and report.pb and report.bvps else 20.0
        finally:
            db.close()
    except Exception:
        base_price = 20.0

    rng = random.Random(code)
    rows = []
    current = max(1.0, base_price)
    today = datetime.now().date()
    day = today - timedelta(days=limit * 2)
    while len(rows) < limit:
        day += timedelta(days=1)
        if day.weekday() >= 5:
            continue
        drift = math.sin(len(rows) / 7) * 0.006 + rng.uniform(-0.018, 0.018)
        prev = current
        current = max(0.5, current * (1 + drift))
        open_price = prev * (1 + rng.uniform(-0.006, 0.006))
        high = max(open_price, current) * (1 + rng.uniform(0.002, 0.018))
        low = min(open_price, current) * (1 - rng.uniform(0.002, 0.018))
        rows.append({
            "date": day.isoformat(),
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(current, 2),
            "volume": int(rng.uniform(80_000, 2_000_000)),
            "turnover": round(current * rng.uniform(80_000, 2_000_000), 2),
            "change_pct": round((current - prev) / prev * 100, 2) if prev else 0.0,
            "turnover_rate": round(rng.uniform(0.2, 4.5), 2),
        })
    return rows
