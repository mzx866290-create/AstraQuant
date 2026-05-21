"""A/B/C tier classifier for the daily observation pool."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

TREND_KEY = "trend"
VOL_PRICE_KEY = "volume_price"
SAFETY_KEY = "safety"

# Current daily-pool score_breakdown uses compact deltas:
# trend is usually 5-10, volume_price is 0-16, safety is 0-25.
TREND_RESONANCE_MIN = 7.5
VOL_PRICE_RESONANCE_MIN = 16.0
SAFETY_RESONANCE_MIN = 23.0
A_SCORE_MIN = 73.0
B_SCORE_MIN = 70.0


def _extract_score_dim(score_breakdown: list[dict] | dict | None, key: str) -> float:
    if not score_breakdown:
        return 0.0
    if isinstance(score_breakdown, dict):
        return float(score_breakdown.get(key, 0) or 0)
    for item in score_breakdown:
        if isinstance(item, dict) and item.get("key") == key:
            return float(item.get("delta") or item.get("value") or 0)
    return 0.0


def _news_payload(item: dict) -> dict:
    value = item.get("value") if isinstance(item, dict) else {}
    return value if isinstance(value, dict) else {}


def _has_news_catalyst(evidence_chain: list[dict] | None) -> bool:
    """Positive catalyst only. Negative news should never promote a stock to A."""
    if not evidence_chain:
        return False
    for item in evidence_chain:
        if not isinstance(item, dict) or item.get("factor") != "news_impact_agent":
            continue
        value = _news_payload(item)
        direction = str(item.get("direction") or value.get("direction") or "neutral").lower()
        relevance = str(value.get("relevance") or "low").lower()
        catalyst_type = str(value.get("catalyst_type") or "none").lower()
        catalyst_strength = str(value.get("catalyst_strength") or "none").lower()
        if direction != "positive":
            continue
        if catalyst_type in {"announcement", "industry_policy"} and catalyst_strength in {"high", "medium"}:
            return True
        if catalyst_type == "news_positive" and relevance in {"high", "medium"}:
            return True
        if relevance == "high":
            return True
    return False


def _has_strong_negative_news(evidence_chain: list[dict] | None) -> bool:
    if not evidence_chain:
        return False
    for item in evidence_chain:
        if not isinstance(item, dict) or item.get("factor") != "news_impact_agent":
            continue
        value = _news_payload(item)
        direction = str(item.get("direction") or value.get("direction") or "neutral").lower()
        relevance = str(value.get("relevance") or "low").lower()
        confidence = str(item.get("confidence") or value.get("confidence") or "medium").lower()
        if direction == "negative" and relevance == "high" and confidence in {"high", "medium"}:
            return True
    return False


def _has_industry_signal(evidence_chain: list[dict] | None) -> bool:
    if not evidence_chain:
        return False
    for item in evidence_chain:
        if not isinstance(item, dict):
            continue
        if item.get("factor") == "news_impact_agent":
            value = _news_payload(item)
            if value.get("has_industry_signal"):
                return True
            if value.get("sector_sentiment") == "positive":
                return True
        if item.get("factor") == "capital_flow" and item.get("direction") == "positive":
            return True
    return False


def _has_capital_flow_confirm(item: dict) -> bool:
    return str(item.get("capital_flow_status") or "").lower() == "confirming"


def _compute_resonance_count(
    rec: dict,
    score_breakdown: list | dict | None,
    evidence_chain: list | None,
) -> int:
    count = 0

    trend_score = _extract_score_dim(score_breakdown, TREND_KEY)
    if trend_score >= TREND_RESONANCE_MIN:
        count += 1

    vol_price_score = _extract_score_dim(score_breakdown, VOL_PRICE_KEY)
    safety_score = _extract_score_dim(score_breakdown, SAFETY_KEY)
    if vol_price_score >= VOL_PRICE_RESONANCE_MIN and safety_score >= SAFETY_RESONANCE_MIN:
        count += 1

    if _has_news_catalyst(evidence_chain):
        count += 1

    if _has_capital_flow_confirm(rec) or _has_industry_signal(evidence_chain):
        count += 1

    return count


def _compute_priority_score(
    rec: dict,
    resonance_count: int,
    evidence_chain: list | None,
    score_breakdown: list | dict | None,
) -> int:
    score = resonance_count * 10

    if rec.get("falsification"):
        score += 10

    if rec.get("bear_case"):
        score += 5

    if evidence_chain:
        for item in evidence_chain:
            if not isinstance(item, dict) or item.get("factor") != "news_impact_agent":
                continue
            value = _news_payload(item)
            if str(item.get("direction") or value.get("direction") or "").lower() != "positive":
                break
            catalyst_type = str(value.get("catalyst_type") or "none").lower()
            if catalyst_type == "announcement":
                score += 15
                break
            if catalyst_type == "industry_policy":
                score += 10
                break
            if catalyst_type == "news_positive":
                score += 5
                break

    if _has_capital_flow_confirm(rec):
        score += 10

    if rec.get("chase_high_penalty"):
        score -= 10

    return max(0, min(100, score))


def classify_tiers(recommendations: list[dict]) -> list[dict]:
    enriched: list[dict] = []

    for rec in recommendations:
        score_breakdown = rec.get("score_breakdown")
        evidence_chain = rec.get("evidence_chain") or []
        resonance = _compute_resonance_count(rec, score_breakdown, evidence_chain)
        priority = _compute_priority_score(rec, resonance, evidence_chain, score_breakdown)
        score = float(rec.get("score") or 0)

        if _has_strong_negative_news(evidence_chain):
            if score >= B_SCORE_MIN and resonance >= 1 and not rec.get("chase_high_penalty"):
                tier = "B"
                tier_reason = "资讯偏负，保留条件观察"
            else:
                tier = "C"
                tier_reason = "资讯偏负或共振不足，低优先级观察"
        elif score >= A_SCORE_MIN and resonance >= 2 and not rec.get("chase_high_penalty"):
            tier = "A"
            tier_reason = _build_tier_reason(rec, score_breakdown, evidence_chain, resonance)
        elif score >= B_SCORE_MIN and resonance >= 1:
            tier = "B"
            tier_reason = _build_tier_reason(rec, score_breakdown, evidence_chain, resonance)
        else:
            tier = "C"
            tier_reason = "技术或资讯共振不足，低优先级观察"

        rec["tier"] = tier
        rec["tier_reason"] = tier_reason
        rec["resonance_count"] = resonance
        rec["priority_score"] = priority
        enriched.append(rec)

    enriched.sort(
        key=lambda x: (
            {"A": 0, "B": 1, "C": 2}.get(x.get("tier", "C"), 2),
            -x.get("priority_score", 0),
            -x.get("score", 0),
        )
    )

    tier_counts = {"A": 0, "B": 0, "C": 0}
    for rec in enriched:
        tier_counts[rec.get("tier", "C")] += 1

    logger.info("Tier classification done: A=%d B=%d C=%d", tier_counts["A"], tier_counts["B"], tier_counts["C"])
    return enriched


def _build_tier_reason(
    rec: dict,
    score_breakdown: Any,
    evidence_chain: list,
    resonance_count: int,
) -> str:
    parts: list[str] = []

    trend_score = _extract_score_dim(score_breakdown, TREND_KEY)
    if trend_score >= TREND_RESONANCE_MIN:
        parts.append("趋势质量共振")

    vol_price_score = _extract_score_dim(score_breakdown, VOL_PRICE_KEY)
    safety_score = _extract_score_dim(score_breakdown, SAFETY_KEY)
    if vol_price_score >= VOL_PRICE_RESONANCE_MIN and safety_score >= SAFETY_RESONANCE_MIN:
        parts.append("量价与安全边际共振")

    if _has_news_catalyst(evidence_chain):
        parts.append("正向资讯催化")

    if _has_capital_flow_confirm(rec):
        parts.append("资金流确认")
    elif _has_industry_signal(evidence_chain):
        parts.append("行业信号支撑")

    if not parts:
        parts.append("通过基础筛选")

    return "，".join(parts)
