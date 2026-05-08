from __future__ import annotations

from backend.services.analysis_service.engine.financial_engine import FinancialAnalysisEngine
from backend.services.analysis_service.engine.indicator_engine import IndicatorEngine
from backend.services.analysis_service.engine.news_sentiment import NewsSentimentEngine

indicator_engine = IndicatorEngine()
financial_engine = FinancialAnalysisEngine()
sentiment_engine = NewsSentimentEngine()


def compute_momentum(kline_data: list[dict]) -> dict:
    """动量评分 (30%) — 基于真实K线涨跌幅。"""
    closes = [item["close"] for item in kline_data if "close" in item]
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


def compute_technical(kline_data: list[dict]) -> dict:
    """技术评分 (25%) — 基于RSI/MACD真实计算。"""
    rsi_values = indicator_engine.rsi(kline_data, 14)
    valid_rsi = [value for value in rsi_values if value is not None]

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


def compute_value(kline_data: list[dict], financial_reports: list[dict]) -> dict:
    """价值评分 (20%) — PE/PB vs 行业估值。"""
    if not financial_reports:
        closes = [item["close"] for item in kline_data if "close" in item]
        if len(closes) >= 250:
            current = closes[-1]
            ma250 = sum(closes[-250:]) / 250
            pb_ratio = current / ma250
            if pb_ratio < 0.7:
                score, detail = 8.0, f"价格远低于年线 ({pb_ratio:.2f}x)，技术面低估"
            elif pb_ratio < 0.9:
                score, detail = 6.5, f"价格低于年线 ({pb_ratio:.2f}x)"
            elif pb_ratio < 1.1:
                score, detail = 5.5, "价格接近年线"
            elif pb_ratio < 1.3:
                score, detail = 4.0, f"价格高于年线 ({pb_ratio:.2f}x)"
            else:
                score, detail = 2.5, f"价格远超年线 ({pb_ratio:.2f}x)，技术面高估"
            return {"score": round(score, 1), "detail": detail, "source": "kline_estimated"}
        return {"score": 5.0, "detail": "财报和长期K线数据不足，默认中性估值", "source": "insufficient"}

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
    return {
        "score": round(score, 1),
        "detail": ", ".join(parts) if parts else "无估值数据",
        "source": "financial_reports",
    }


def compute_quality(kline_data: list[dict], financial_reports: list[dict]) -> dict:
    """质量评分 (15%) — ROE/ROA/毛利率/F-Score。"""
    if not financial_reports:
        closes = [item["close"] for item in kline_data if "close" in item]
        if len(closes) >= 60:
            trend = sum(
                1
                for idx in range(len(closes) - 20, len(closes))
                if closes[idx] > closes[idx - 1]
            ) / min(len(closes) - 20, 20)
            score = 4.0 + trend * 4.0
            return {
                "score": round(score, 1),
                "detail": f"近20日上涨比例{trend*100:.0f}%(技术面估算)",
                "source": "kline_estimated",
            }
        return {"score": 5.0, "detail": "财报和趋势数据不足，默认中性质量", "source": "insufficient"}

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
        f_result = financial_engine.piotroski_f_score(financial_reports[:2])
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
    return {
        "score": round(score, 1),
        "detail": "; ".join(parts) if parts else "无质量数据",
        "source": "financial_reports",
    }


def compute_sentiment(kline_data: list[dict], news_list: list[dict], money_flow_context: dict) -> dict:
    """情绪评分 (10%) — 资金流向 + 新闻情感 + 换手率变化。"""
    parts = []
    score = 5.0
    has_data = False
    money_flow_data = money_flow_context.get("data", [])
    warnings = list(money_flow_context.get("warnings", []))

    if news_list:
        summary = sentiment_engine.summarize_sentiment(news_list, days=7)
        if summary["total"] > 0:
            has_data = True
            pos_ratio = summary.get("positive_ratio", 0)
            neg_ratio = summary.get("negative_ratio", 0)
            sent_bias = (pos_ratio - neg_ratio) / 100
            score += sent_bias * 4.0
            parts.append(f"新闻正面率{pos_ratio:.0f}%,负面率{neg_ratio:.0f}%")

    if money_flow_data:
        has_data = True
        recent = money_flow_data[-5:]
        net_flow = sum((item.get("main_inflow") or 0) for item in recent)
        if net_flow > 0:
            score += 1.5
            parts.append("主力净流入(近5日)")
        else:
            score -= 0.5
            parts.append("主力净流出(近5日)")

    if kline_data and len(kline_data) >= 10:
        recent_tor = [item.get("turnover_rate", 0) for item in kline_data[-5:] if item.get("turnover_rate")]
        older_tor = [item.get("turnover_rate", 0) for item in kline_data[-10:-5] if item.get("turnover_rate")]
        if recent_tor and older_tor:
            has_data = True
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

    if money_flow_context.get("status") != "ok":
        parts.append("资金流向暂不可用")

    score = max(0, min(10, score))
    source = "mixed" if has_data else "insufficient"
    if warnings:
        source = "partial_without_money_flow" if has_data else "insufficient_without_money_flow"
    status = "ok" if has_data else "insufficient"
    if warnings:
        status = "partial" if has_data else "unavailable"

    return {
        "score": round(score, 1),
        "detail": "; ".join(parts) if parts else "无情绪数据",
        "source": source,
        "status": status,
        "warnings": warnings,
        "data_quality": {
            "money_flow": money_flow_context.get("data_quality", {}),
        },
    }


def to_rating(score: float) -> dict:
    if score >= 8.5:
        return {"text": "重点关注", "level": "A+"}
    if score >= 7.0:
        return {"text": "值得观察", "level": "A"}
    if score >= 5.5:
        return {"text": "中性", "level": "B"}
    if score >= 4.0:
        return {"text": "谨慎", "level": "C"}
    return {"text": "风险", "level": "D"}
