"""
行情API - A股实时行情 + 资金流向
"""
from fastapi import APIRouter, HTTPException
from typing import Optional

router = APIRouter(tags=["行情"])


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
        from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource
        em = EastMoneySource()
        try:
            result = await em.fetch_realtime_quote(symbol)
            await em.close()
            if result.get("price") and result["price"] > 0:
                return result
        except Exception:
            pass
        # 实时行情不可用时从日K线中提取最新数据
        kline = await em.fetch_daily_kline(symbol, adjust="1")
        await em.close()
        if kline and len(kline) > 0:
            latest = kline[-1]
            prev = kline[-2] if len(kline) > 1 else latest
            name = await _get_stock_name(symbol)
            return {
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
            }
    except Exception as e:
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
        result = await em.fetch_money_flow(symbol)
        await em.close()
        return {"symbol": symbol, "days": days, "data": result, "source": "eastmoney"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"资金流向获取失败: {str(e)}")
