"""趋势评分排序器 — 对观察池候选股进行趋势、位置、量价质量评分"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def score_anomalies(candidates: list[dict], top_n: int = 20) -> list[dict]:
    """
    对趋势候选股打分排序，取 top_n。

    总分 100，维度：
    - 趋势质量 (30分)：线性回归趋势、R²、MA 多头排列
    - 安全边际 (25分)：近 5 日未过热、贴近 MA20、回撤风险较低
    - 量价配合 (20分)：放量上涨、缩量回调、温和量比
    - 技术位置 (15分)：MA60 支撑、波动收窄、突破但未远离均线
    - 市场关注度 (10分)：换手率适中、流动性不过冷不过热
    """
    if not candidates:
        return []

    scored = []
    for item in candidates:
        score_detail = _compute_score(item)
        item["anomaly_score"] = score_detail["total"]
        item["score_breakdown"] = score_detail
        scored.append(item)

    scored.sort(key=lambda x: x["anomaly_score"], reverse=True)
    result = scored[:top_n]
    logger.info("Scored %s candidates, selected top %s", len(candidates), len(result))
    return result


def _compute_score(item: dict) -> dict:
    trend = _score_trend_quality(item)
    safety = _score_safety_margin(item)
    vol_price = _score_volume_price(item)
    tech_pos = _score_technical_position(item)
    attention = _score_market_attention(item)
    bucket_fit = _score_bucket_fit(item)

    total = min(100.0, round(trend + safety + vol_price + tech_pos + attention + bucket_fit, 1))

    return {
        "total": total,
        "trend_quality": round(trend, 1),
        "safety_margin": round(safety, 1),
        "volume_price": round(vol_price, 1),
        "technical_position": round(tech_pos, 1),
        "market_attention": round(attention, 1),
        "bucket_fit": round(bucket_fit, 1),
    }


def _score_bucket_fit(item: dict) -> float:
    bucket = item.get("observation_bucket")
    change_pct = item.get("change_pct") or 0
    trend = item.get("trend_features") or {}
    quality = item.get("quality_features") or {}

    if bucket == "trend_strength":
        if -1 <= change_pct <= 5 and trend.get("recent_5d_gain", 0) <= 12:
            return 6
        return 3
    if bucket == "pullback_support":
        score = 8
        if quality.get("controlled_pullback"):
            score += 4
        if -3 <= change_pct <= 1:
            score += 3
        return min(score, 15)
    if bucket == "oversold_reversal":
        score = 7
        if change_pct >= -2:
            score += 3
        if 0.8 <= (item.get("vol_ratio_5d") or 1.0) <= 2.5:
            score += 3
        return min(score, 13)
    return 0.0


def _score_trend_quality(item: dict) -> float:
    score = 0.0
    trend = item.get("trend_features") or {}
    reasons = item.get("anomaly_reasons") or []
    slope_pct = trend.get("slope_pct") or 0
    r2 = trend.get("r2") or 0

    if slope_pct > 0:
        score += min(10, slope_pct * 8)

    if r2 >= 0.7:
        score += 10
    elif r2 >= 0.55:
        score += 8
    elif r2 >= 0.3:
        score += 5

    if "MA多头排列" in reasons:
        score += 6
    if "趋势稳定" in reasons:
        score += 4

    return min(score, 30)


def _score_safety_margin(item: dict) -> float:
    score = 0.0
    trend = item.get("trend_features") or {}
    distance = trend.get("distance_ma20")
    recent_5d_gain = trend.get("recent_5d_gain")

    if distance is None:
        close = item.get("close") or 0
        ma20 = item.get("ma20") or 0
        distance = (close - ma20) / ma20 if close and ma20 else 1

    if distance <= 0.03:
        score += 12
    elif distance <= 0.06:
        score += 10
    elif distance <= 0.10:
        score += 7
    elif distance <= 0.15:
        score += 4

    if recent_5d_gain is None:
        recent_5d_gain = 0

    if 0 <= recent_5d_gain <= 6:
        score += 10
    elif -3 <= recent_5d_gain < 0:
        score += 8
    elif 6 < recent_5d_gain <= 10:
        score += 6
    elif 10 < recent_5d_gain <= 15:
        score += 3

    change_pct = item.get("change_pct") or 0
    if -2 <= change_pct <= 4:
        score += 3

    return min(score, 25)


def _score_volume_price(item: dict) -> float:
    score = 0.0
    quality = item.get("quality_features") or {}
    vol_ratio = item.get("vol_ratio_5d") or 1.0
    change_pct = item.get("change_pct") or 0

    if quality.get("volume_price_confirmed"):
        score += 7
    if quality.get("controlled_pullback"):
        score += 5
    if 1.1 <= vol_ratio <= 2.5 and change_pct >= 0:
        score += 6
    elif 0.8 <= vol_ratio < 1.1 and -1 <= change_pct <= 3:
        score += 4
    elif 2.5 < vol_ratio <= 3.5 and 0 <= change_pct <= 3:
        score += 3
    elif vol_ratio > 3.5:
        score += 1

    if quality.get("momentum_moderate"):
        score += 2

    return min(score, 20)


def _score_technical_position(item: dict) -> float:
    score = 0.0
    quality = item.get("quality_features") or {}
    reasons = item.get("anomaly_reasons") or []
    close = item.get("close") or 0
    ma60 = item.get("ma60") or 0

    if ma60 and close > ma60:
        score += 4
        distance_60 = (close - ma60) / ma60
        if distance_60 <= 0.15:
            score += 3

    if quality.get("volatility_contracting"):
        score += 5
    if "贴近MA20" in reasons:
        score += 3
    elif "价格位置健康" in reasons:
        score += 2

    return min(score, 15)


def _score_market_attention(item: dict) -> float:
    quality = item.get("quality_features") or {}
    turnover_rate = item.get("turnover_rate") or 0

    if quality.get("turnover_healthy") and 2.0 <= turnover_rate <= 8.0:
        return 10
    if quality.get("turnover_healthy"):
        return 8
    if 0.5 <= turnover_rate < 1.0 or 10.0 < turnover_rate <= 12.0:
        return 5
    if turnover_rate < 0.5:
        return 2
    return 3
