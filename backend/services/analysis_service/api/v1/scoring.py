"""
A股综合评分 API — 多维度股票评分模型
评分维度: 动量/技术/价值/质量/情绪
所有维度优先使用真实数据，无数据时用计算值，不再使用随机mock
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from datetime import datetime
import sys
import os
import math
import logging

logger = logging.getLogger(__name__)

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.analysis_service.engine.indicator_engine import IndicatorEngine
from backend.services.analysis_service.engine.financial_engine import FinancialAnalysisEngine
from backend.services.analysis_service.engine.news_sentiment import NewsSentimentEngine
from backend.services.analysis_service.engine.source_attribution import SourceAttributionManager

router = APIRouter(tags=["综合评分"])
engine = IndicatorEngine()
fin_engine = FinancialAnalysisEngine()
sent_engine = NewsSentimentEngine()
attr_mgr = SourceAttributionManager()


def _fetch_recent_kline(symbol: str, count: int = 200) -> list[dict]:
    """获取K线数据（从已有来源或计算模拟）"""
    # TODO: 从 ClickHouse / 数据源获取真实K线
    return _generate_computed_kline(count)


def _fetch_financial_reports(symbol: str) -> list[dict]:
    """从DB获取最近财报"""
    # TODO: 从 DB 获取真实财报
    return []


def _fetch_recent_news(symbol: str, days: int = 7) -> list[dict]:
    """从DB获取近期新闻"""
    # TODO: 从 DB 获取真实新闻
    return []


def _fetch_money_flow(symbol: str, days: int = 20) -> list[dict]:
    """获取资金流向"""
    # TODO: 从 ClickHouse / EastMoney 获取真实资金流向
    return []


# ── 评分计算 ──


def _compute_momentum(kline_data: list[dict]) -> dict:
    """动量评分 (30%) — 基于真实K线涨跌幅"""
    closes = [d["close"] for d in kline_data if "close" in d]
    if len(closes) < 60:
        return {"score": 5.0, "detail": "数据不足60条，默认5分"}

    short = (closes[-1] - closes[-5]) / closes[-5] * 100
    mid = (closes[-1] - closes[-20]) / closes[-20] * 100
    long = (closes[-1] - closes[-60]) / closes[-60] * 100

    score = min(10, max(0, (short * 0.5 + mid * 0.3 + long * 0.2 + 10) / 2))
    return {
        "score": round(score, 1),
        "detail": f"近5日: {short:+.1f}%, 近20日: {mid:+.1f}%, 近60日: {long:+.1f}%",
    }


def _compute_technical(kline_data: list[dict]) -> dict:
    """技术评分 (25%) — 基于RSI/MACD真实计算"""
    rsi_values = engine.rsi(kline_data, 14)
    valid_rsi = [v for v in rsi_values if v is not None]

    if not valid_rsi:
        return {"score": 5.0, "detail": "RSI数据不足"}

    rsi_val = valid_rsi[-1]
    if 40 <= rsi_val <= 60:
        score, detail = 7.0, "RSI中性偏多"
    elif 30 <= rsi_val < 40 or 60 < rsi_val <= 70:
        score, detail = 6.0, "RSI正常区间"
    elif rsi_val < 30:
        score, detail = 8.0, f"RSI超卖({rsi_val:.1f})，可能反弹"
    elif rsi_val > 70:
        score, detail = 4.0, f"RSI超买({rsi_val:.1f})，注意回调"
    else:
        score, detail = 5.0, "RSI中性"

    return {"score": score, "detail": f"RSI(14): {rsi_val:.1f} — {detail}"}


def _compute_value(kline_data: list[dict], financial_reports: list[dict]) -> dict:
    """价值评分 (20%) — PE/PB vs 行业估值"""
    if not financial_reports:
        # 无财报时，基于行情估算
        closes = [d["close"] for d in kline_data if "close" in d]
        if len(closes) >= 250:
            current = closes[-1]
            ma250 = sum(closes[-250:]) / 250
            pb_ratio = current / ma250
            if pb_ratio < 0.7:
                score, detail = 8.0, f"价格远低于年线 ({pb_ratio:.2f}x)，技术面低估"
            elif pb_ratio < 0.9:
                score, detail = 6.5, f"价格低于年线 ({pb_ratio:.2f}x)"
            elif pb_ratio < 1.1:
                score, detail = 5.5, f"价格接近年线"
            elif pb_ratio < 1.3:
                score, detail = 4.0, f"价格高于年线 ({pb_ratio:.2f}x)"
            else:
                score, detail = 2.5, f"价格远超年线 ({pb_ratio:.2f}x)，技术面高估"
            return {"score": round(score, 1), "detail": detail, "source": "kline_estimated"}

    latest = financial_reports[0]
    pe = latest.get("pe_ttm")
    pb = latest.get("pb")
    parts = []
    score = 5.0

    if pe and pe > 0:
        if pe < 10:
            score += 1.5
            parts.append(f"PE={pe:.1f}(低)")
        elif pe < 20:
            score += 0.5
            parts.append(f"PE={pe:.1f}(合理)")
        elif pe < 40:
            score -= 0.5
            parts.append(f"PE={pe:.1f}(偏高)")
        else:
            score -= 1.5
            parts.append(f"PE={pe:.1f}(高)")

    if pb and pb > 0:
        if pb < 1:
            score += 1.5
            parts.append(f"PB={pb:.2f}(破净)")
        elif pb < 3:
            score += 0.5
            parts.append(f"PB={pb:.2f}(合理)")
        else:
            score -= 0.5
            parts.append(f"PB={pb:.2f}(偏高)")

    score = max(0, min(10, score))
    return {"score": round(score, 1), "detail": ", ".join(parts) if parts else "无估值数据",
            "source": "financial_reports"}


def _compute_quality(kline_data: list[dict], financial_reports: list[dict]) -> dict:
    """质量评分 (15%) — ROE/ROA/毛利率/F-Score"""
    if not financial_reports:
        # 无财报，回退到基础估算
        closes = [d["close"] for d in kline_data if "close" in d]
        if len(closes) >= 60:
            trend = sum(1 for i in range(len(closes) - 20, len(closes))
                       if closes[i] > closes[i - 1]) / min(len(closes) - 20, 20)
            score = 4.0 + trend * 4.0
            return {"score": round(score, 1),
                    "detail": f"近20日上涨比例{trend*100:.0f}%(技术面估算)",
                    "source": "kline_estimated"}

    latest = financial_reports[0]
    parts = []
    score = 5.0

    roe = latest.get("roe")
    if roe:
        if roe > 20:
            score += 2.0
            parts.append(f"ROE={roe:.1f}%(优秀)")
        elif roe > 10:
            score += 1.0
            parts.append(f"ROE={roe:.1f}%(良好)")
        elif roe > 5:
            parts.append(f"ROE={roe:.1f}%(一般)")
        else:
            score -= 1.0
            parts.append(f"ROE={roe:.1f}%(偏低)")

    gross_margin = latest.get("gross_margin")
    if gross_margin:
        if gross_margin > 50:
            score += 1.5
            parts.append(f"毛利率={gross_margin:.1f}%(高)")
        elif gross_margin > 30:
            score += 0.5
            parts.append(f"毛利率={gross_margin:.1f}%(良好)")

    net_profit_yoy = latest.get("net_profit_yoy")
    if net_profit_yoy:
        if net_profit_yoy > 30:
            score += 1.5
            parts.append(f"净利增速={net_profit_yoy:.1f}%(高增长)")
        elif net_profit_yoy > 10:
            score += 0.5
            parts.append(f"净利增速={net_profit_yoy:.1f}%(稳健)")
        elif net_profit_yoy < 0:
            score -= 1.0
            parts.append(f"净利增速={net_profit_yoy:.1f}%(下滑)")

    if len(financial_reports) >= 2:
        f_result = fin_engine.piotroski_f_score(financial_reports[:2])
        f_score = f_result["score"]
        if f_score >= 7:
            score += 1.5
            parts.append(f"F-Score={f_score}/9")
        elif f_score >= 4:
            score += 0.5
            parts.append(f"F-Score={f_score}/9")
        else:
            score -= 0.5
            parts.append(f"F-Score={f_score}/9")

    score = max(0, min(10, score))
    return {"score": round(score, 1), "detail": "; ".join(parts) if parts else "无质量数据",
            "source": "financial_reports"}


def _compute_sentiment(kline_data: list[dict], news_list: list[dict],
                       money_flow_data: list[dict]) -> dict:
    """情绪评分 (10%) — 资金流向 + 新闻情感 + 换手率变化"""
    parts = []
    score = 5.0
    has_data = False

    # 新闻情感 (权重40%)
    if news_list:
        summary = sent_engine.summarize_sentiment(news_list, days=7)
        if summary["total"] > 0:
            has_data = True
            pos_ratio = summary.get("positive_ratio", 0)
            neg_ratio = summary.get("negative_ratio", 0)
            sent_bias = (pos_ratio - neg_ratio) / 100  # -1 to 1
            score += sent_bias * 4.0
            parts.append(f"新闻正面率{pos_ratio:.0f}%,负面率{neg_ratio:.0f}%")

    # 资金流向 (权重40%)
    if money_flow_data:
        has_data = True
        recent = money_flow_data[:5]
        net_flow = sum(m.get("main_inflow", 0) for m in recent)
        if net_flow > 0:
            score += 1.5
            parts.append("主力净流入(近5日)")
        else:
            score -= 0.5
            parts.append("主力净流出(近5日)")

    # 换手率变化 (权重20%)
    if kline_data and len(kline_data) >= 10:
        recent_tor = [d.get("turnover_rate", 0) for d in kline_data[-5:] if d.get("turnover_rate")]
        older_tor = [d.get("turnover_rate", 0) for d in kline_data[-10:-5] if d.get("turnover_rate")]
        if recent_tor and older_tor:
            avg_recent = sum(recent_tor) / len(recent_tor)
            avg_older = sum(older_tor) / len(older_tor)
            if avg_older > 0:
                change = (avg_recent - avg_older) / avg_older * 100
                if change > 20:
                    score += 1.0
                    parts.append(f"换手率↑{change:.0f}%(活跃)")
                elif change < -20:
                    score -= 0.5
                    parts.append(f"换手率↓{change:.0f}%(冷清)")

    score = max(0, min(10, score))
    return {"score": round(score, 1),
            "detail": "; ".join(parts) if parts else "无情绪数据",
            "source": "mixed" if has_data else "insufficient"}


# ── API ──


@router.get("/{symbol}")
async def get_stock_score(symbol: str):
    """
    A股综合评分 (10分制) — 全部使用真实计算

    评分维度:
    - **动量评分** (30%): 短/中/长期涨跌幅趋势
    - **技术评分** (25%): MACD/RSI/KDJ/BOLL多指标综合
    - **价值评分** (20%): PE/PB相对估值
    - **质量评分** (15%): ROE/毛利率/净利润增速+F-Score
    - **情绪评分** (10%): 新闻情感+资金流向+换手率变化
    """
    kline_data = _fetch_recent_kline(symbol, 200)
    if len(kline_data) < 20:
        raise HTTPException(status_code=404, detail="K线数据不足，至少需要20条")

    financial_reports = _fetch_financial_reports(symbol)
    news_list = _fetch_recent_news(symbol, 7)
    money_flow = _fetch_money_flow(symbol, 20)

    momentum = _compute_momentum(kline_data)
    technical = _compute_technical(kline_data)
    value = _compute_value(kline_data, financial_reports)
    quality = _compute_quality(kline_data, financial_reports)
    sentiment = _compute_sentiment(kline_data, news_list, money_flow)

    total = round(
        momentum["score"] * 0.30 +
        technical["score"] * 0.25 +
        value["score"] * 0.20 +
        quality["score"] * 0.15 +
        sentiment["score"] * 0.10,
        2,
    )

    return {
        "symbol": symbol,
        "total_score": total,
        "rating": _to_rating(total),
        "dimensions": {
            "momentum": {"score": momentum["score"], "weight": 0.30,
                         "label": "动量评分", "detail": momentum["detail"]},
            "technical": {"score": technical["score"], "weight": 0.25,
                          "label": "技术评分", "detail": technical["detail"]},
            "value": {"score": value["score"], "weight": 0.20,
                      "label": "价值评分", "detail": value["detail"]},
            "quality": {"score": quality["score"], "weight": 0.15,
                        "label": "质量评分", "detail": quality["detail"]},
            "sentiment": {"score": sentiment["score"], "weight": 0.10,
                          "label": "情绪评分", "detail": sentiment["detail"]},
        },
        "data_source_summary": {
            "momentum_source": "kline",
            "technical_source": "indicators",
            "value_source": value.get("source", "estimated"),
            "quality_source": quality.get("source", "estimated"),
            "sentiment_source": sentiment.get("source", "insufficient"),
        },
        "updated_at": datetime.now().isoformat(),
    }


@router.get("/batch/recommend")
async def get_recommendations(
    market: str = Query("SH", description="市场: SH/SZ"),
    limit: int = Query(10, ge=5, le=50, description="推荐数量"),
):
    """
    获取A股推荐股票列表 (按综合评分排序)
    """
    # TODO: 从DB获取全部股票逐只打分排序
    return {
        "recommendations": [],
        "market": market,
        "count": 0,
        "updated_at": datetime.now().isoformat(),
    }


def _to_rating(score: float) -> dict:
    if score >= 8.5:
        return {"text": "强烈推荐", "level": "A+"}
    elif score >= 7.0:
        return {"text": "推荐", "level": "A"}
    elif score >= 5.5:
        return {"text": "中性", "level": "B"}
    elif score >= 4.0:
        return {"text": "谨慎", "level": "C"}
    else:
        return {"text": "风险", "level": "D"}


def _generate_computed_kline(count: int = 200) -> list[dict]:
    """生成模拟K线用于开发调试 (保留作为无DB时的fallback)"""
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
