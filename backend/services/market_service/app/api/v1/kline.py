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
from backend.services.market_service.app.services import kline_service

router = APIRouter(tags=["K线"])
engine = IndicatorEngine()
_build_local_kline = kline_service.build_local_kline


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


_INTRADAY_PERIODS = {
    KLinePeriod.MIN_1,
    KLinePeriod.MIN_5,
    KLinePeriod.MIN_15,
    KLinePeriod.MIN_30,
    KLinePeriod.MIN_60,
}
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
    if not isinstance(period, KLinePeriod):
        period = KLinePeriod.DAILY
    if not isinstance(adjust, AdjustFlag):
        adjust = AdjustFlag.FORWARD
    if not isinstance(limit, int):
        limit = 200
    if not isinstance(indicators, str):
        indicators = None
    kline_data, source = await kline_service.load_kline_data(symbol, period.value, adjust.value, limit)
    if period in _INTRADAY_PERIODS and not kline_data:
        raise HTTPException(status_code=503, detail="minute kline source is temporarily unavailable")

    latest_date = kline_data[-1].get("date") if kline_data else None
    result = {
        "symbol": symbol,
        "period": period.value,
        "count": len(kline_data),
        "source": source,
        "updated_at": str(latest_date) if latest_date else None,
        "data": kline_data,
        "data_quality": kline_service.build_data_quality(source, period.value, kline_data),
    }

    # 计算技术指标
    if indicators:
        ind_list = [i.strip() for i in indicators.split(",") if i.strip()]
        computed = engine.compute_all(kline_data, ind_list)
        result["indicators"] = computed

    return result
