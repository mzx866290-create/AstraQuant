"""
技术分析 API - 单股/批量技术指标计算
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from enum import Enum
import sys
import os

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.analysis_service.engine.indicator_engine import IndicatorEngine

router = APIRouter(tags=["技术分析"])
engine = IndicatorEngine()

VALID_INDICATORS = {"ma5", "ma10", "ma20", "ma60", "ma120",
                    "ema5", "ema10", "ema12", "ema20", "ema26",
                    "macd", "boll", "kdj", "rsi", "vol5", "vol10", "vol20"}


async def _fetch_kline(symbol: str, limit: int = 200) -> list[dict]:
    from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource

    em = EastMoneySource()
    try:
        data = await em.fetch_daily_kline(symbol)
    finally:
        await em.close()
    return data[-limit:] if len(data) > limit else data


@router.get("/{symbol}")
async def get_technical_analysis(
    symbol: str,
    indicators: str = Query("ma5,ma20,macd,boll,kdj,rsi",
                            description="指标列表,逗号分隔"),
    period: str = Query("1d", description="K线周期"),
    limit: int = Query(200, ge=50, le=1000, description="计算周期数"),
):
    """
    获取A股技术指标分析

    - **symbol**: 股票代码 (600519.SH)
    - **indicators**: ma5,ma10,ma20,ma60,ma120,ema5,ema12,ema26,macd,boll,kdj,rsi,vol5,vol10,vol20
    - **period**: K线周期 (1d/1w/1M)

    返回完整的指标计算结果:
    - 均线: MA5/MA10/MA20/MA60 值数组
    - MACD: DIF/DEA/柱状图
    - BOLL: 上轨/中轨/下轨
    - KDJ: K/D/J 值
    - RSI: 值数组
    - 成交量均线: VOL5/VOL10/VOL20
    """
    ind_list = [i.strip().lower() for i in indicators.split(",") if i.strip()]
    invalid = [i for i in ind_list if i not in VALID_INDICATORS]
    if invalid:
        raise HTTPException(status_code=400,
                            detail=f"不支持的指标: {', '.join(invalid)}. 支持: {', '.join(sorted(VALID_INDICATORS))}")

    try:
        kline_data = await _fetch_kline(symbol, limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"K线数据源不可用: {e}")
    if len(kline_data) < 20:
        raise HTTPException(status_code=404, detail="真实K线数据不足，无法计算技术指标")

    result = engine.compute_all(kline_data, ind_list)

    return {
        "symbol": symbol,
        "period": period,
        "count": len(kline_data),
        "source": "eastmoney",
        "indicators": result,
    }


@router.get("/{symbol}/single")
async def get_single_indicator(
    symbol: str,
    indicator: str = Query("macd", description="指标名称"),
    period: int = Query(14, ge=2, le=250, description="指标周期"),
):
    """
    获取单个指标的详细计算结果

    - **indicator**: 指标名 (macd/rsi/boll/kdj/ma/ema)
    - **period**: 周期参数
    """
    ind_lower = indicator.lower()

    try:
        kline_data = await _fetch_kline(symbol, 200)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"K线数据源不可用: {e}")
    if len(kline_data) < 20:
        raise HTTPException(status_code=404, detail="真实K线数据不足，无法计算技术指标")

    if ind_lower == "macd":
        fast = period
        slow = min(period * 2 + 4, 52)
        sig = min(period - 3, 9)
        result = engine.macd(kline_data, fast=fast, slow=slow, signal=sig)
    elif ind_lower == "rsi":
        result = {"rsi": engine.rsi(kline_data, period)}
    elif ind_lower == "boll":
        result = engine.boll(kline_data, period)
    elif ind_lower == "kdj":
        result = engine.kdj(kline_data, period)
    elif ind_lower in ("ma", "ema"):
        fn = engine.ma if ind_lower == "ma" else engine.ema
        result = {f"{ind_lower}{period}": fn(kline_data, period)}
    else:
        raise HTTPException(status_code=400, detail=f"不支持的指标: {indicator}")

    return {
        "symbol": symbol,
        "indicator": indicator,
        "period": period,
        "data": result,
    }
