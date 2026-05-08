"""
龙虎榜API - A股龙虎榜数据
"""
from datetime import date, datetime
import math
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["龙虎榜"])


def _data_quality(
    source: str,
    status: str = "ok",
    confidence: float = 0.9,
    warnings: Optional[list[str]] = None,
    updated_at: Optional[str] = None,
) -> dict:
    return {
        "source": source,
        "status": status,
        "updated_at": updated_at or datetime.now().isoformat(),
        "freshness": "daily",
        "confidence": confidence,
        "is_fallback": False,
        "warnings": warnings or [],
    }


def _pick(row: dict, *names: str):
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name)
    return None


def _safe_float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_round(value, digits: int = 2) -> Optional[float]:
    number = _safe_float(value)
    return round(number, digits) if number is not None else None


def _normalize_code(value) -> str:
    text = str(value or "")
    match = re.search(r"\d{6}", text)
    return match.group(0) if match else ""


def _market_suffix(code: str) -> str:
    if code.startswith(("4", "8", "920")):
        return "BJ"
    if code.startswith(("6", "9", "5")):
        return "SH"
    if code.startswith(("0", "1", "2", "3")):
        return "SZ"
    return ""


def _normalize_trade_date(value) -> str:
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def _normalize_row(row: dict) -> dict:
    code = _normalize_code(_pick(row, "代码", "股票代码", "证券代码", "symbol", "ts_code"))
    market = _market_suffix(code)
    symbol = f"{code}.{market}" if code and market else code
    return {
        "symbol": symbol,
        "code": code,
        "name": _pick(row, "名称", "股票简称", "证券简称", "name") or "",
        "trade_date": _normalize_trade_date(_pick(row, "上榜日", "交易日期", "trade_date", "date")),
        "reason": _pick(row, "上榜原因", "上榜理由", "reason") or "",
        "interpretation": _pick(row, "解读", "说明", "interpretation") or "",
        "close": _safe_round(_pick(row, "收盘价", "close")),
        "change_pct": _safe_round(_pick(row, "涨跌幅", "涨跌幅(%)", "pct_chg", "change_pct")),
        "net_buy": _safe_round(_pick(row, "龙虎榜净买额", "净买额", "net_buy")),
        "buy_amount": _safe_round(_pick(row, "龙虎榜买入额", "买入额", "buy_amount")),
        "sell_amount": _safe_round(_pick(row, "龙虎榜卖出额", "卖出额", "sell_amount")),
        "turnover": _safe_round(_pick(row, "龙虎榜成交额", "成交额", "turnover")),
        "market_turnover": _safe_round(_pick(row, "市场总成交额", "总成交额", "market_turnover")),
        "net_buy_ratio": _safe_round(_pick(row, "净买额占总成交比", "净买额占比", "net_buy_ratio")),
        "turnover_ratio": _safe_round(_pick(row, "成交额占总成交比", "成交额占比", "turnover_ratio")),
        "turnover_rate": _safe_round(_pick(row, "换手率", "换手率(%)", "turnover_rate")),
        "source": "akshare-eastmoney",
    }


def _normalize_rows(rows: list[dict], limit: int, symbol: Optional[str] = None) -> list[dict]:
    clean_symbol = symbol[:6] if symbol else None
    normalized = []
    for row in rows:
        item = _normalize_row(row)
        if clean_symbol and item["code"] != clean_symbol:
            continue
        if item["code"]:
            normalized.append(item)
        if len(normalized) >= limit:
            break
    return normalized


async def _fetch_akshare_dragon_tiger(trade_date: Optional[date]) -> list[dict]:
    from backend.services.data_crawler.sources.akshare_source import AKShareSource

    source = AKShareSource()
    return await source.fetch_dragon_tiger(trade_date.isoformat() if trade_date else "")


async def _fetch_akshare_stock_dragon_tiger(symbol: str, days: int) -> list[dict]:
    from backend.services.data_crawler.sources.akshare_source import AKShareSource

    source = AKShareSource()
    return await source.fetch_stock_dragon_tiger(symbol, days=days)


@router.get("")
async def get_dragon_tiger(
    trade_date: Optional[date] = Query(None, description="交易日期"),
    limit: int = Query(50, ge=1, le=200),
):
    """获取龙虎榜数据"""
    if not isinstance(trade_date, date):
        trade_date = None
    if not isinstance(limit, int):
        limit = 50

    try:
        raw_rows = await _fetch_akshare_dragon_tiger(trade_date)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"dragon tiger source unavailable: {exc}") from exc

    rows = _normalize_rows(raw_rows, limit)
    warnings = [] if rows else ["dragon_tiger_empty"]
    requested_date = trade_date.isoformat() if trade_date else datetime.now().date().isoformat()
    return {
        "trade_date": requested_date,
        "count": len(rows),
        "source": "akshare-eastmoney",
        "data": rows,
        "data_quality": _data_quality(
            source="akshare-eastmoney",
            status="ok" if rows else "unavailable",
            confidence=0.9 if rows else 0.15,
            warnings=warnings,
            updated_at=requested_date,
        ),
    }


@router.get("/{symbol}")
async def get_stock_dragon_tiger(
    symbol: str,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
):
    """获取个股龙虎榜历史"""
    if not isinstance(days, int):
        days = 30
    if not isinstance(limit, int):
        limit = 50

    clean_symbol = symbol[:6]
    if not clean_symbol.isdigit():
        raise HTTPException(status_code=400, detail="无效的股票代码")

    try:
        raw_rows = await _fetch_akshare_stock_dragon_tiger(clean_symbol, days)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"dragon tiger source unavailable: {exc}") from exc

    rows = _normalize_rows(raw_rows, limit, symbol=clean_symbol)
    warnings = [] if rows else ["dragon_tiger_empty"]
    return {
        "symbol": symbol,
        "days": days,
        "count": len(rows),
        "source": "akshare-eastmoney",
        "data": rows,
        "data_quality": _data_quality(
            source="akshare-eastmoney",
            status="ok" if rows else "unavailable",
            confidence=0.9 if rows else 0.15,
            warnings=warnings,
            updated_at=rows[0]["trade_date"] if rows else None,
        ),
    }
