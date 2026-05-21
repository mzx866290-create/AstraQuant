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


def _extract_code(symbol: str) -> str:
    text = (symbol or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    for prefix in ("SH", "SZ", "BJ"):
        if text.startswith(prefix):
            text = text[2:]
            break
    return "".join(ch for ch in text if ch.isdigit())[:6]


def _extract_market(symbol: str) -> str | None:
    text = (symbol or "").strip().upper()
    if "." in text:
        suffix = text.rsplit(".", 1)[1]
        return "SH" if suffix == "SS" else suffix
    for prefix in ("SH", "SZ", "BJ"):
        if text.startswith(prefix):
            return prefix
    return None


def _infer_market(code: str, market: str | None = None) -> str:
    normalized = (market or "").strip().upper()
    if normalized == "SS":
        normalized = "SH"
    if normalized in {"SH", "SZ", "BJ"}:
        return normalized
    if code.startswith(("4", "8", "920")):
        return "BJ"
    if code.startswith(("6", "9", "5")):
        return "SH"
    return "SZ"


def _normalize_symbol(symbol: str) -> str:
    code = _extract_code(symbol)
    return f"{code}.{_infer_market(code, _extract_market(symbol))}" if code else ""


def _normalize_symbol_list(symbols: str) -> list[str]:
    normalized: list[str] = []
    seen = set()
    for item in symbols.split(","):
        symbol = _normalize_symbol(item)
        if symbol and symbol not in seen:
            normalized.append(symbol)
            seen.add(symbol)
    return normalized


async def _fetch_kline(symbol: str, limit: int = 120) -> list[dict]:
    """获取K线数据，东方财富优先，失败后 fallback 到新浪"""
    from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource

    eastmoney_error: Exception | None = None
    try:
        em = EastMoneySource()
        try:
            data = await em.fetch_daily_kline(symbol)
        finally:
            await em.close()
        if data:
            return data[-limit:] if len(data) > limit else data
    except Exception as e:
        eastmoney_error = e
        logger.info("%s 东方财富K线失败，尝试新浪/腾讯兜底: %s", symbol, e)

    from backend.services.data_crawler.sources.sina_tencent_source import SinaTencentSource

    try:
        st = SinaTencentSource()
        data = await st.fetch_daily_kline(symbol)
        if data:
            return data[-limit:] if len(data) > limit else data
    except Exception as e:
        logger.warning("%s K线数据源均失败，东方财富: %s；新浪/腾讯: %s", symbol, eastmoney_error, e)

    return []


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
    symbol_list = _normalize_symbol_list(symbols)
    if len(symbol_list) > 5:
        raise HTTPException(status_code=400, detail="最多对比5只股票")
    if not symbol_list:
        raise HTTPException(status_code=400, detail="请提供股票代码")

    ind_list = [i.strip().lower() for i in indicators.split(",") if i.strip()]

    result = {}
    for sym in symbol_list:
        try:
            kline_data = await _fetch_kline(sym, limit)
        except Exception as e:
            logger.warning(f"{sym} K线获取失败: {e}")
            kline_data = []
        if len(kline_data) < 2:
            result[sym] = {
                "latest_indicators": {},
                "performance": {},
                "data_points": len(kline_data),
                "latest_price": None,
                "error": "真实K线数据不足",
            }
            continue
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
    symbol_list = _normalize_symbol_list(symbols)
    period_list = [p.strip() for p in periods.split(",") if p.strip()]
    period_map = {"1d": 1, "5d": 5, "20d": 20, "60d": 60,
                  "120d": 120, "250d": 250}

    data = {}
    for sym in symbol_list:
        max_period = max(period_map.get(p, 1) for p in period_list)
        try:
            kline_data = await _fetch_kline(sym, max_period + 10)
        except Exception as e:
            logger.warning(f"{sym} K线获取失败: {e}")
            kline_data = []
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
    symbol_list = _normalize_symbol_list(symbols)
    if len(symbol_list) > 5:
        raise HTTPException(status_code=400, detail="最多对比5只股票")

    from backend.shared.database import SessionLocal
    from backend.shared.models import FinancialReport

    db = SessionLocal()
    try:
        fundamental_data = {}
        for sym in symbol_list:
            code = _extract_code(sym)
            latest = (
                db.query(FinancialReport)
                .filter(FinancialReport.stock_symbol == code)
                .order_by(FinancialReport.report_date.desc())
                .first()
            )
            fundamental_data[sym] = {
                "pe": latest.pe_ttm if latest else None,
                "pb": latest.pb if latest else None,
                "roe": latest.roe if latest else None,
                "gross_margin": latest.gross_margin if latest else None,
                "net_profit_yoy": latest.net_profit_yoy if latest else None,
                "revenue_yoy": latest.revenue_yoy if latest else None,
                "report_date": latest.report_date.isoformat() if latest and latest.report_date else None,
            }
    finally:
        db.close()

    return {
        "fundamentals": fundamental_data,
        "count": len(symbol_list),
        "source": "financial_reports",
        "updated_at": datetime.now().isoformat(),
    }
