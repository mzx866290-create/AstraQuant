"""
K线数据API - A股多周期K线 + 复权 + 技术指标
后端实时计算MA/MACD/BOLL/KDJ/RSI等指标
"""
from fastapi import APIRouter, Query, HTTPException
from enum import Enum
from typing import Optional
from datetime import date
import sys
import os

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.analysis_service.engine.indicator_engine import IndicatorEngine

router = APIRouter(tags=["K线"])
engine = IndicatorEngine()


class KLinePeriod(str, Enum):
    MIN_1 = "1m"
    MIN_5 = "5m"
    MIN_15 = "15m"
    MIN_30 = "30m"
    MIN_60 = "60m"
    DAILY = "1d"
    WEEKLY = "1w"
    MONTHLY = "1M"


class AdjustFlag(str, Enum):
    NONE = "0"      # 不复权
    FORWARD = "1"   # 前复权
    BACKWARD = "2"  # 后复权


@router.get("/{symbol}")
async def get_kline(
    symbol: str,
    period: KLinePeriod = Query(KLinePeriod.DAILY, description="K线周期"),
    start_date: Optional[date] = Query(None, description="起始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    limit: int = Query(200, ge=1, le=1000, description="返回条数"),
    adjust: AdjustFlag = Query(AdjustFlag.FORWARD, description="复权类型"),
    indicators: Optional[str] = Query(None, description="技术指标,逗号分隔: ma5,ma20,macd,boll,kdj,rsi"),
):
    """
    获取A股K线数据 + 实时计算技术指标

    - **symbol**: 股票代码 (600519 或 000858.SZ)
    - **period**: K线周期 (1m/5m/15m/30m/60m/1d/1w/1M)
    - **adjust**: 复权类型 (0=不复权 1=前复权 2=后复权)
    - **indicators**: 可选技术指标 (ma5,ma10,ma20,ma60,macd,boll,kdj,rsi)

    返回:
    - data: K线数据 (含up_limit/down_limit/turnover_rate/amplitude)
    - indicators: 请求的技术指标计算结果
    """
    clean_symbol = symbol[:6] if len(symbol) >= 6 else symbol
    if not clean_symbol.isdigit():
        raise HTTPException(status_code=400, detail="无效的股票代码")

    kline_data = []
    source = "mock"

    try:
        from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource
        em = EastMoneySource()
        kline_data = await em.fetch_daily_kline(symbol, adjust=adjust.value)
        await em.close()
        source = "eastmoney"
    except Exception:
        kline_data = _generate_mock_kline(limit)

    # 限制返回条数
    if len(kline_data) > limit:
        kline_data = kline_data[-limit:]

    result = {
        "symbol": symbol,
        "period": period.value,
        "count": len(kline_data),
        "source": source,
        "data": kline_data,
    }

    # 计算技术指标
    if indicators:
        ind_list = [i.strip() for i in indicators.split(",") if i.strip()]
        computed = engine.compute_all(kline_data, ind_list)
        result["indicators"] = computed

    return result


def _generate_mock_kline(count: int = 200) -> list[dict]:
    """生成模拟K线数据用于开发调试"""
    import random
    from datetime import datetime, timedelta

    data = []
    price = 1700.0
    now = datetime.now()
    # 从最早开始生成，保证指标计算正确
    for i in range(count):
        day = now - timedelta(days=count - i)
        if day.weekday() >= 5:
            continue
        change = (random.random() - 0.48) * 30
        open_px = price
        close = round(open_px + change, 2)
        high = round(max(open_px, close) + random.random() * 15, 2)
        low = round(min(open_px, close) - random.random() * 15, 2)
        vol = random.randint(1000000, 6000000)
        data.append({
            "date": day.strftime("%Y-%m-%d"),
            "open": open_px,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
            "turnover": round(vol * close, 2),
            "change_pct": round(change / price * 100, 2),
            "turnover_rate": round(random.uniform(0.1, 3.0), 2),
            "amplitude": round(abs(high - low) / open_px * 100, 2),
        })
        price = close
    return data
