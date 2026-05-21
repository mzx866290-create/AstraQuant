"""
行情API - A股实时行情 + 资金流向
"""
from fastapi import APIRouter, HTTPException
from typing import Optional
from datetime import datetime
import logging

from backend.services.market_service.app.api.v1.kline import _build_local_kline
from backend.services.market_service.app.utils.symbols import bj_legacy_920_symbol

logger = logging.getLogger(__name__)

router = APIRouter(tags=["行情"])


def _data_quality(source: str, updated_at: Optional[str] = None, freshness: str = "realtime",
                  confidence: float = 0.9, is_fallback: bool = False,
                  warnings: Optional[list[str]] = None,
                  status: Optional[str] = None,
                  warning: Optional[str] = None) -> dict:
    quality = {
        "source": source,
        "updated_at": updated_at or datetime.now().isoformat(),
        "freshness": freshness,
        "confidence": confidence,
        "is_fallback": is_fallback,
        "warnings": warnings or [],
    }
    if status:
        quality["status"] = status
    if warning:
        quality["warning"] = warning
    return quality


def _with_quote_quality(result: dict, source: str, freshness: str = "realtime",
                        confidence: float = 0.9, is_fallback: bool = False,
                        warnings: Optional[list[str]] = None) -> dict:
    quality_warnings = list(warnings or [])
    price = _safe_float(result.get("price"))
    open_price = _safe_float(result.get("open"))
    high = _safe_float(result.get("high"))
    low = _safe_float(result.get("low"))
    volume = _safe_float(result.get("volume"))
    if price == 0:
        quality_warnings.append("quote_price_zero")
    if price and any(value is None or value <= 0 for value in (open_price, high, low)):
        quality_warnings.append("quote_trade_fields_missing_or_zero")
    if price and volume == 0:
        quality_warnings.append("quote_volume_zero_or_suspended")
    quality_warnings = list(dict.fromkeys(quality_warnings))
    degraded = bool(quality_warnings)
    result["source"] = result.get("source") or source
    result["updated_at"] = str(result.get("timestamp")) if result.get("timestamp") else datetime.now().isoformat()
    result["data_quality"] = _data_quality(
        source=result["source"],
        updated_at=result["updated_at"],
        freshness=freshness,
        confidence=min(confidence, 0.65) if degraded else confidence,
        is_fallback=is_fallback,
        warnings=quality_warnings,
        status="degraded" if degraded else "ok",
    )
    return result


def _safe_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quote_lookup_symbols(symbol: str) -> list[tuple[str, str]]:
    alias = bj_legacy_920_symbol(symbol)
    if alias and alias.upper() != (symbol or "").upper():
        return [(alias, alias), (symbol, "")]
    return [(symbol, "")]


def _mark_resolved_symbol(result: dict, requested_symbol: str, resolved_symbol: str) -> dict:
    if resolved_symbol:
        result["requested_symbol"] = requested_symbol
        result["resolved_symbol"] = resolved_symbol
    return result


async def _get_stock_name(symbol: str) -> str:
    """从数据库查询股票名称"""
    code = symbol[:6]
    try:
        from backend.shared.database import SessionLocal
        from backend.shared.models import Stock
        db = SessionLocal()
        try:
            stock = db.query(Stock).filter(Stock.symbol.like(f"{code}%")).first()
            return stock.name if stock else symbol
        finally:
            db.close()
    except Exception:
        return symbol


@router.get("/{symbol}")
async def get_quote(symbol: str):
    """
    获取A股实时行情

    - **symbol**: 股票代码 (600519 或 600519.SH)
    - 返回: 最新价/涨跌幅/成交量/换手率/PE/市值等
    """
    from backend.services.data_crawler.sources.sina_tencent_source import SinaTencentSource

    for candidate, resolved_symbol in _quote_lookup_symbols(symbol):
        try:
            st = SinaTencentSource()
            result = await st.fetch_realtime_quote(candidate)
            if result.get("price") and result["price"] > 0:
                result = _mark_resolved_symbol(result, symbol, resolved_symbol)
                return _with_quote_quality(result, "sina-tencent", confidence=0.95)
        except Exception as e:
            logger.warning("sina-tencent quote failed for %s: %s", candidate, e)

    try:
        from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource
        em = EastMoneySource()
        try:
            result = await em.fetch_realtime_quote(symbol)
            if result.get("price") and result["price"] > 0:
                await em.close()
                return _with_quote_quality(result, "eastmoney", confidence=0.92)
        except Exception as e:
            logger.warning("eastmoney realtime quote failed for %s: %s", symbol, e)
        # 实时行情不可用时从日K线中提取最新数据
        kline = await em.fetch_daily_kline(symbol, adjust="1")
        await em.close()
        if kline and len(kline) > 0:
            latest = kline[-1]
            prev = kline[-2] if len(kline) > 1 else latest
            name = await _get_stock_name(symbol)
            return _with_quote_quality({
                "symbol": symbol,
                "name": name,
                "price": latest["close"],
                "change": round(latest["close"] - prev["close"], 2),
                "change_pct": latest.get("change_pct", 0),
                "high": latest["high"],
                "low": latest["low"],
                "open": latest["open"],
                "volume": latest["volume"],
                "turnover": latest.get("turnover", 0),
                "turnover_rate": latest.get("turnover_rate", 0) if latest.get("turnover_rate") else 0.0,
                "pe_ttm": 0.0,
                "total_mv": 0.0,
                "circ_mv": 0.0,
                "up_limit": round(latest["close"] * 1.1, 2),
                "down_limit": round(latest["close"] * 0.9, 2),
                "timestamp": latest["date"],
                "source": "eastmoney-kline",
            }, "eastmoney-kline", freshness="daily-kline", confidence=0.75, is_fallback=True,
                warnings=["realtime quote unavailable; derived from latest daily kline"])
    except Exception as e:
        logger.warning("eastmoney kline fallback failed for %s: %s", symbol, e)

    try:
        from backend.services.data_crawler.sources.akshare_source import AKShareSource
        ak = AKShareSource()
        result = await ak.fetch_realtime_quote(symbol)
        if result.get("price") and result["price"] > 0:
            result["source"] = "akshare"
            return _with_quote_quality(result, "akshare", confidence=0.85)
    except Exception as e:
        logger.warning("akshare realtime quote failed for %s: %s", symbol, e)

    try:
        from backend.services.data_crawler.sources.akshare_source import AKShareSource
        ak = AKShareSource()
        kline = await ak.fetch_daily_kline(symbol, adjust="1")
        if kline:
            latest = kline[-1]
            prev = kline[-2] if len(kline) > 1 else latest
            name = await _get_stock_name(symbol)
            return _with_quote_quality({
                "symbol": symbol,
                "name": name,
                "price": latest["close"],
                "change": round(latest["close"] - prev["close"], 2),
                "change_pct": latest.get("change_pct", 0),
                "high": latest["high"],
                "low": latest["low"],
                "open": latest["open"],
                "volume": latest["volume"],
                "turnover": latest.get("turnover", 0),
                "turnover_rate": latest.get("turnover_rate", 0) if latest.get("turnover_rate") else 0.0,
                "pe_ttm": 0.0,
                "total_mv": 0.0,
                "circ_mv": 0.0,
                "up_limit": round(latest["close"] * 1.1, 2),
                "down_limit": round(latest["close"] * 0.9, 2),
                "timestamp": latest["date"],
                "source": "akshare-kline",
            }, "akshare-kline", freshness="daily-kline", confidence=0.7, is_fallback=True,
                warnings=["realtime quote unavailable; derived from latest daily kline"])
    except Exception as e:
        logger.warning("akshare kline fallback failed for %s: %s", symbol, e)

    try:
        kline = await _build_local_kline(symbol, 2)
        latest = kline[-1]
        prev = kline[-2] if len(kline) > 1 else latest
        name = await _get_stock_name(symbol)
        return _with_quote_quality({
            "symbol": symbol,
            "name": name,
            "price": latest["close"],
            "change": round(latest["close"] - prev["close"], 2),
            "change_pct": latest.get("change_pct", 0),
            "high": latest["high"],
            "low": latest["low"],
            "open": latest["open"],
            "volume": latest["volume"],
            "turnover": latest.get("turnover", 0),
            "turnover_rate": latest.get("turnover_rate", 0) if latest.get("turnover_rate") else 0.0,
            "pe_ttm": 0.0,
            "total_mv": 0.0,
            "circ_mv": 0.0,
            "up_limit": round(latest["close"] * 1.1, 2),
            "down_limit": round(latest["close"] * 0.9, 2),
            "timestamp": latest["date"],
            "source": "local-fallback",
        }, "local-fallback", freshness="generated", confidence=0.35, is_fallback=True,
            warnings=["local fallback quote generated from local kline; not a live market quote"])
    except Exception:
        pass

    raise HTTPException(status_code=502, detail=f"行情数据获取失败: 数据源不可用")


@router.get("/{symbol}/money-flow")
async def get_money_flow(symbol: str, days: int = 20):
    """
    获取A股资金流向

    - **symbol**: 股票代码
    - **days**: 返回天数 (默认20)
    - 返回: 主力/超大单/大单/中单/小单净流入
    """
    try:
        from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource
        em = EastMoneySource()
        try:
            result = await em.fetch_money_flow(symbol, limit=days)
        finally:
            await em.close()
        if not result:
            return {
                "symbol": symbol,
                "days": days,
                "data": [],
                "source": "eastmoney",
                "updated_at": datetime.now().isoformat(),
                "data_quality": _data_quality(
                    "eastmoney",
                    freshness="empty",
                    confidence=0.2,
                    status="empty",
                    warning="money_flow_empty",
                    warnings=["money_flow_empty"],
                ),
            }
        latest_date = result[-1].get("date") if result else None
        return {
            "symbol": symbol,
            "days": days,
            "data": result,
            "source": "eastmoney",
            "updated_at": latest_date or datetime.now().isoformat(),
            "data_quality": _data_quality("eastmoney", updated_at=latest_date, freshness="recent", confidence=0.85, status="ok"),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"资金流向获取失败: {str(e)}")
