"""
多股对比 API — 横向比较多只股票的指标/走势/评分
"""
from fastapi import APIRouter, Query, HTTPException
from datetime import datetime
import sys
import os
import logging

logger = logging.getLogger(__name__)

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.analysis_service.engine.indicator_engine import IndicatorEngine

router = APIRouter(tags=["多股对比"])
engine = IndicatorEngine()


def _fetch_kline(symbol: str, limit: int = 120) -> list[dict]:
    """获取真实K线数据"""
    # TODO: 从数据源获取真实K线
    return _generate_fallback_kline(limit)


@router.get("")
async def compare_stocks(
    symbols: str = Query(..., description="股票代码,逗号分隔,最多5只"),
    indicators: str = Query("ma5,ma20,macd,rsi", description="对比指标"),
    limit: int = Query(120, ge=20, le=500),
):
    """
    横向对比多只股票的技术指标

    - **symbols**: 600519,000858,000651 (最多5只)
    - **indicators**: ma5,ma20,macd,rsi,boll,kdj

    返回每只股票的指标并排数据
    """
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if len(symbol_list) > 5:
        raise HTTPException(status_code=400, detail="最多对比5只股票")
    if not symbol_list:
        raise HTTPException(status_code=400, detail="请提供股票代码")

    ind_list = [i.strip().lower() for i in indicators.split(",") if i.strip()]

    result = {}
    for sym in symbol_list:
        kline_data = _fetch_kline(sym, limit)
        computed = engine.compute_all(kline_data, ind_list)

        # 提取最新值用于对比
        latest = {}
        for ind_name, values in computed.items():
            if isinstance(values, dict):
                latest[ind_name] = {}
                for sub_key, sub_vals in values.items():
                    valid = [v for v in sub_vals if v is not None]
                    latest[ind_name][sub_key] = valid[-1] if valid else None
            else:
                valid = [v for v in values if v is not None]
                latest[ind_name] = valid[-1] if valid else None

        # 计算区间涨跌幅
        closes = [d["close"] for d in kline_data if "close" in d]
        performance = {}
        for period_name, offset in [("5d", 5), ("20d", 20), ("60d", 60)]:
            if len(closes) >= offset:
                perf = (closes[-1] - closes[-offset]) / closes[-offset] * 100
                performance[period_name] = round(perf, 2)
            else:
                performance[period_name] = None

        result[sym] = {
            "latest_indicators": latest,
            "performance": performance,
            "data_points": len(kline_data),
            "latest_price": closes[-1] if closes else None,
        }

    return {
        "compare": result,
        "indicators": ind_list,
        "count": len(symbol_list),
        "updated_at": datetime.now().isoformat(),
    }


@router.get("/performance")
async def compare_performance(
    symbols: str = Query(..., description="股票代码,逗号分隔"),
    periods: str = Query("1d,5d,20d,60d", description="区间: 1d/5d/20d/60d"),
):
    """
    多只股票区间涨跌幅对比
    """
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    period_list = [p.strip() for p in periods.split(",") if p.strip()]
    period_map = {"1d": 1, "5d": 5, "20d": 20, "60d": 60,
                  "120d": 120, "250d": 250}

    data = {}
    for sym in symbol_list:
        max_period = max(period_map.get(p, 1) for p in period_list)
        kline_data = _fetch_kline(sym, max_period + 10)
        closes = [d["close"] for d in kline_data if "close" in d]

        sym_perf = {}
        for p in period_list:
            offset = period_map.get(p, 1)
            if len(closes) > offset:
                chg = (closes[-1] - closes[-offset]) / closes[-offset] * 100
                sym_perf[p] = round(chg, 2)
            else:
                sym_perf[p] = None
        data[sym] = sym_perf

    return {
        "symbols": symbol_list,
        "periods": period_list,
        "data": data,
        "updated_at": datetime.now().isoformat(),
    }


@router.get("/fundamentals")
async def compare_fundamentals(
    symbols: str = Query(..., description="股票代码,逗号分隔"),
):
    """
    多只股票基本面横向对比

    对比维度: PE/PB/ROE/毛利率/净利润增速/营收增速
    """
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if len(symbol_list) > 5:
        raise HTTPException(status_code=400, detail="最多对比5只股票")

    # TODO: 从DB获取真实财报数据
    fundamental_data = {}
    for sym in symbol_list:
        fundamental_data[sym] = {
            "pe": None, "pb": None, "roe": None,
            "gross_margin": None, "net_profit_yoy": None,
            "revenue_yoy": None,
        }

    return {
        "fundamentals": fundamental_data,
        "count": len(symbol_list),
        "source": "pending_real_data",
        "updated_at": datetime.now().isoformat(),
    }


def _generate_fallback_kline(count: int = 200) -> list[dict]:
    """Fallback: 生成模拟K线 (DB不可用时的开发模式)"""
    import random
    from datetime import datetime, timedelta
    data = []
    price = 50.0
    now = datetime.now()
    for i in range(count):
        day = now - timedelta(days=count - i)
        if day.weekday() >= 5:
            continue
        change = (random.random() - 0.48) * 3
        open_px = price
        close = round(open_px + change, 2)
        high = round(max(open_px, close) + random.random() * 1.5, 2)
        low = round(min(open_px, close) - random.random() * 1.5, 2)
        data.append({"date": day.strftime("%Y-%m-%d"), "open": open_px,
                     "high": high, "low": low, "close": close,
                     "volume": random.randint(100000, 5000000),
                     "turnover": 0, "change_pct": 0})
        price = close
    return data
