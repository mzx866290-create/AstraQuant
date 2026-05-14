"""
行情API - A股实时行情 + 资金流向
"""
from fastapi import APIRouter, HTTPException
from typing import Optional
from datetime import datetime

from backend.services.market_service.app.api.v1.kline import _build_local_kline

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
    price = result.get("price")
    if price == 0:
        quality_warnings.append("price is 0; quote may be unavailable or suspended")
    result["source"] = result.get("source") or source
    result["updated_at"] = str(result.get("timestamp")) if result.get("timestamp") else datetime.now().isoformat()
    result["data_quality"] = _data_quality(
        source=result["source"],
        updated_at=result["updated_at"],
        freshness=freshness,
        confidence=confidence,
        is_fallback=is_fallback,
        warnings=quality_warnings,
    )
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
    try:
        from backend.services.data_crawler.sources.sina_tencent_source import SinaTencentSource
        st = SinaTencentSource()
        result = await st.fetch_realtime_quote(symbol)
        if result.get("price") and result["price"] > 0:
            return _with_quote_quality(result, "sina-tencent", confidence=0.95)
    except Exception:
        pass

    try:
        from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource
        em = EastMoneySource()
        try:
            result = await em.fetch_realtime_quote(symbol)
            if result.get("price") and result["price"] > 0:
                await em.close()
                return _with_quote_quality(result, "eastmoney", confidence=0.92)
        except Exception:
            pass
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
    except Exception:
        pass

    try:
        from backend.services.data_crawler.sources.akshare_source import AKShareSource
        ak = AKShareSource()
        result = await ak.fetch_realtime_quote(symbol)
        if result.get("price") and result["price"] > 0:
            result["source"] = "akshare"
            return _with_quote_quality(result, "akshare", confidence=0.85)
    except Exception:
        pass

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
    except Exception:
        pass

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
        if result == []:
            return {
                "symbol": symbol,
                "days": days,
                "data": [],
                "source": "eastmoney",
                "updated_at": datetime.now().isoformat(),
                "data_quality": _data_quality(
                    "eastmoney",
                    freshness="missing",
                    confidence=0.05,
                    status="unavailable",
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
