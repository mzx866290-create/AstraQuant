"""Second-pass optimizer for the daily observation pool.

This layer keeps the fast anomaly screener intact, then makes the pool safer
and more useful before it reaches users: news freshness, market regime,
industry concentration, and historical review feedback are folded into tier,
priority, and action metadata.
"""
from __future__ import annotations

import logging
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from sqlalchemy import inspect

from backend.shared.database import SessionLocal, engine
from backend.shared.models import ObservationReview, ResearchObservation

logger = logging.getLogger(__name__)

OPTIMIZER_VERSION = "observation_pool_optimizer_v1"
NEWS_FACTOR = "news_impact_agent"
ACTION_WATCH_ONLY = "只看不追"
ACTION_NEWS_VERIFY = "消息验证"
ACTION_PULLBACK = "回踩承接"
ACTION_BREAKOUT = "放量突破"

_TIER_RANK = {"A": 0, "B": 1, "C": 2}
_TABLE_CHECK_CACHE: dict[str, bool] = {}


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, min_value), max_value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def _has_table(table_name: str) -> bool:
    cached = _TABLE_CHECK_CACHE.get(table_name)
    if cached is not None:
        return cached
    try:
        exists = inspect(engine).has_table(table_name)
    except Exception:
        exists = False
    _TABLE_CHECK_CACHE[table_name] = exists
    return exists


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _dict_value(item: dict, key: str) -> dict:
    value = item.get(key)
    return value if isinstance(value, dict) else {}


def _news_items(evidence_chain: Any) -> list[dict]:
    if not isinstance(evidence_chain, list):
        return []
    return [
        item for item in evidence_chain
        if isinstance(item, dict) and item.get("factor") == NEWS_FACTOR
    ]


def _news_freshness(generated_at: datetime | None, now: datetime) -> tuple[float, float | None, str]:
    if not generated_at:
        return 0.7, None, "unknown_generated_at"
    age_hours = max((now - generated_at).total_seconds() / 3600, 0.0)
    if age_hours <= 12:
        return 1.0, round(age_hours, 2), "fresh"
    if age_hours <= 24:
        return 0.85, round(age_hours, 2), "overnight"
    if age_hours <= 48:
        return 0.65, round(age_hours, 2), "aging"
    if age_hours <= 72:
        return 0.4, round(age_hours, 2), "stale"
    return 0.2, round(age_hours, 2), "expired"


def _weight_level(value: Any, default: int = 1) -> int:
    text = str(value or "").lower()
    if text == "high":
        return 3
    if text == "medium":
        return 2
    if text == "low":
        return 1
    return default


def _news_profile(rec: dict, now: datetime) -> dict:
    items = _news_items(rec.get("evidence_chain"))
    if not items:
        return {
            "has_news": False,
            "direction": "none",
            "freshness_score": 0.0,
            "age_hours": None,
            "freshness_label": "none",
            "strength": 0.0,
            "summary": "",
        }

    profiles = []
    for item in items:
        value = _dict_value(item, "value")
        direction = str(item.get("direction") or value.get("direction") or "neutral").lower()
        relevance = str(value.get("relevance") or "medium").lower()
        confidence = str(item.get("confidence") or value.get("confidence") or "medium").lower()
        generated_at = _parse_dt(item.get("generated_at"))
        freshness_score, age_hours, freshness_label = _news_freshness(generated_at, now)
        sign = 1 if direction == "positive" else -1 if direction == "negative" else 0
        impact = _safe_float(item.get("impact"), 0.0)
        strength = abs(impact) + _weight_level(relevance) + _weight_level(confidence)
        profiles.append(
            {
                "direction": direction,
                "relevance": relevance,
                "confidence": confidence,
                "freshness_score": freshness_score,
                "age_hours": age_hours,
                "freshness_label": freshness_label,
                "signed_strength": sign * strength,
                "strength": strength,
                "summary": str(value.get("summary") or item.get("explanation") or "")[:160],
            }
        )

    strongest = max(profiles, key=lambda item: abs(item["signed_strength"]))
    signed_total = sum(item["signed_strength"] * item["freshness_score"] for item in profiles)
    if signed_total > 1:
        direction = "positive"
    elif signed_total < -1:
        direction = "negative"
    else:
        direction = "neutral"

    return {
        "has_news": True,
        "direction": direction,
        "freshness_score": round(max(item["freshness_score"] for item in profiles), 4),
        "age_hours": strongest["age_hours"],
        "freshness_label": strongest["freshness_label"],
        "strength": round(abs(signed_total), 4),
        "relevance": strongest["relevance"],
        "confidence": strongest["confidence"],
        "summary": strongest["summary"],
        "strong_negative": (
            direction == "negative"
            and strongest["relevance"] == "high"
            and strongest["confidence"] in {"high", "medium"}
            and strongest["freshness_score"] >= 0.4
        ),
    }


def _industry_key(rec: dict) -> str:
    industry_filter = rec.get("industry_filter") if isinstance(rec.get("industry_filter"), dict) else {}
    return str(
        rec.get("industry_name")
        or rec.get("sector")
        or industry_filter.get("industry_name")
        or "UNKNOWN"
    )


def _downgrade_tier(tier: str | None, steps: int = 1) -> str:
    ordered = ["A", "B", "C"]
    current = ordered.index(tier) if tier in ordered else 2
    return ordered[min(current + steps, len(ordered) - 1)]


def _max_tier(tier: str | None, maximum: str) -> str:
    current_rank = _TIER_RANK.get(str(tier or "C"), 2)
    max_rank = _TIER_RANK.get(maximum, 2)
    if current_rank < max_rank:
        return maximum
    return str(tier or "C")


def _append_risk_warning(rec: dict, warning: str) -> None:
    old = str(rec.get("risk_warning") or "").strip()
    if not old:
        rec["risk_warning"] = warning
    elif warning not in old:
        rec["risk_warning"] = f"{old}；{warning}"


def fetch_review_feedback_for_symbols(
    symbols: list[str],
    *,
    lookback_days: int = 90,
    min_reviews: int = 2,
) -> dict[str, dict]:
    """Return recent review feedback keyed by symbol. Fail closed to empty."""
    unique_symbols = sorted({str(symbol).strip() for symbol in symbols if str(symbol or "").strip()})
    if not unique_symbols:
        return {}
    if not _has_table("research_observations") or not _has_table("observation_reviews"):
        return {}

    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(lookback_days, 1))
        rows = (
            db.query(ResearchObservation, ObservationReview)
            .join(ObservationReview, ObservationReview.observation_id == ResearchObservation.id)
            .filter(ResearchObservation.symbol.in_(unique_symbols))
            .filter(ResearchObservation.snapshot_date >= cutoff)
            .all()
        )
    except Exception as exc:
        logger.debug("fetch review feedback failed: %s", exc)
        return {}
    finally:
        db.close()

    by_symbol: dict[str, list[ObservationReview]] = defaultdict(list)
    for observation, review in rows:
        by_symbol[observation.symbol].append(review)

    result: dict[str, dict] = {}
    for symbol, reviews in by_symbol.items():
        returns = [float(review.return_pct) for review in reviews if review.return_pct is not None]
        drawdowns = [float(review.max_drawdown_pct) for review in reviews if review.max_drawdown_pct is not None]
        if len(returns) < min_reviews:
            continue
        positives = sum(1 for value in returns if value > 0)
        result[symbol] = {
            "reviews": len(reviews),
            "return_samples": len(returns),
            "win_rate": round(positives / len(returns), 4),
            "avg_return_pct": round(mean(returns), 4),
            "worst_return_pct": round(min(returns), 4),
            "max_drawdown_pct": round(min(drawdowns), 4) if drawdowns else None,
            "falsification_count": sum(1 for review in reviews if review.falsification_triggered),
        }
    return result


def _apply_news_adjustment(rec: dict, profile: dict, adjustments: list[str]) -> int:
    if not profile.get("has_news"):
        return 0

    delta = 0
    direction = profile.get("direction")
    freshness = _safe_float(profile.get("freshness_score"), 0.0)

    if profile.get("strong_negative"):
        old_tier = rec.get("tier")
        rec["tier"] = _max_tier(rec.get("tier"), "B")
        if old_tier != rec.get("tier"):
            adjustments.append("高相关负面资讯：A档降为条件观察")
        rec["observation_action"] = ACTION_NEWS_VERIFY
        _append_risk_warning(rec, "隔夜资讯偏负，开盘前必须复核公告和成交承接")
        adjustments.append("负面资讯触发开盘前复核")
        return -18

    if direction == "negative":
        rec["tier"] = _max_tier(rec.get("tier"), "B")
        rec["observation_action"] = ACTION_NEWS_VERIFY
        _append_risk_warning(rec, "资讯影响偏负，先验证再观察")
        adjustments.append("负面资讯降低优先级")
        return -10

    if direction == "positive":
        if freshness >= 0.65:
            delta = min(8, int(round(profile.get("strength", 0) * 1.2)))
            if delta > 0:
                adjustments.append("新鲜正向资讯提高优先级")
        else:
            delta = -4
            rec["observation_action"] = ACTION_NEWS_VERIFY
            adjustments.append("正向资讯已过期，转为消息验证")
        return delta

    if freshness < 0.4:
        adjustments.append("资讯过期，不再给优先级加成")
        return -2
    return 0


def _apply_regime_adjustment(rec: dict, regime: str, adjustments: list[str]) -> int:
    bucket = str(rec.get("observation_bucket") or "trend_strength")
    action = str(rec.get("observation_action") or "")
    change_pct = _safe_float(rec.get("change_pct"), 0.0)
    delta = 0

    if regime == "weak_market":
        delta -= 5
        if bucket == "trend_strength" or action == ACTION_BREAKOUT:
            delta -= 5
            rec["tier"] = _max_tier(rec.get("tier"), "B")
            adjustments.append("弱市压低强势突破类优先级")
        if change_pct >= 5 or rec.get("chase_high_penalty"):
            delta -= 5
            rec["observation_action"] = ACTION_WATCH_ONLY
            _append_risk_warning(rec, "弱市高开或追高风险较高，只看不追")
            adjustments.append("弱市追高风险转为只看不追")
        if bucket == "pullback_support":
            delta += 3
            adjustments.append("弱市优先保留回调承接")
    elif regime == "range_bound":
        if action == ACTION_BREAKOUT and change_pct >= 3:
            delta -= 4
            adjustments.append("震荡市降低突破追涨优先级")
        if bucket == "pullback_support":
            delta += 3
            adjustments.append("震荡市偏向回调承接")
    elif regime == "strong_trend":
        if bucket == "trend_strength":
            delta += 4
            adjustments.append("强趋势环境保留强势延续")
        elif bucket == "pullback_support":
            delta += 3
            adjustments.append("强趋势环境保留回踩机会")

    return delta


def _apply_review_adjustment(rec: dict, feedback: dict | None, adjustments: list[str]) -> int:
    if not feedback:
        return 0

    rec["review_feedback"] = feedback
    reviews = _safe_int(feedback.get("return_samples"))
    win_rate = _safe_float(feedback.get("win_rate"), 0.0)
    avg_return = _safe_float(feedback.get("avg_return_pct"), 0.0)
    falsifications = _safe_int(feedback.get("falsification_count"))

    if reviews >= 3 and (win_rate < 0.35 or avg_return <= -2.0 or falsifications >= 2):
        rec["tier"] = _max_tier(rec.get("tier"), "B")
        adjustments.append("历史复盘表现偏弱，降低优先级")
        return -7
    if reviews >= 3 and win_rate >= 0.55 and avg_return >= 1.0:
        adjustments.append("历史复盘表现较好，提高优先级")
        return 4
    return 0


def _sort_key(rec: dict) -> tuple[int, int, float]:
    return (
        _TIER_RANK.get(str(rec.get("tier") or "C"), 2),
        -_safe_int(rec.get("priority_score"), 0),
        -_safe_float(rec.get("score"), 0.0),
    )


def _apply_diversification(
    recommendations: list[dict],
    *,
    summary: dict,
) -> list[dict]:
    if not recommendations:
        return recommendations

    total = len(recommendations)
    cap = _env_int(
        "OBS_POOL_MAX_PER_INDUSTRY",
        max(3, math.ceil(total * 0.18)),
        min_value=2,
        max_value=max(total, 2),
    )
    counts: Counter[str] = Counter()
    penalties = 0
    concentrated: Counter[str] = Counter()

    for rec in sorted(recommendations, key=_sort_key):
        industry = _industry_key(rec)
        rec["industry_name"] = industry if industry != "UNKNOWN" else rec.get("industry_name")
        counts[industry] += 1
        rank = counts[industry]
        penalty = 0
        if industry != "UNKNOWN" and rank > cap:
            penalty = min(15, 4 * (rank - cap))
            rec["priority_score"] = max(0, _safe_int(rec.get("priority_score")) - penalty)
            rec["diversification_penalty"] = penalty
            concentrated[industry] += 1
            penalties += 1
            optimizer = _dict_value(rec, "pool_optimizer")
            optimizer.setdefault("adjustments", []).append(f"行业集中度超过上限，优先级 -{penalty}")
            rec["pool_optimizer"] = optimizer
            if rec.get("tier") == "A" and rank > cap + 1:
                rec["tier"] = "B"
                optimizer["tier_after"] = "B"
        else:
            rec["diversification_penalty"] = 0

    summary["diversification"] = {
        "industry_cap": cap,
        "industries": len([key for key in counts if key != "UNKNOWN"]),
        "max_industry_count": max(counts.values()) if counts else 0,
        "penalties_applied": penalties,
        "concentrated_industries": dict(concentrated.most_common(5)),
    }
    return sorted(recommendations, key=_sort_key)


def optimize_observation_pool(
    recommendations: list[dict],
    market_regime: dict | None = None,
    *,
    mode: str = "base",
    review_feedback: dict[str, dict] | None = None,
    now: datetime | None = None,
) -> tuple[list[dict], dict]:
    """Apply a deterministic second-pass optimizer to observation-pool rows."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    regime_payload = market_regime or {}
    regime = str(regime_payload.get("regime") or "range_bound")
    confidence = str(regime_payload.get("confidence") or "unknown")
    feedback_by_symbol = review_feedback or {}

    if not recommendations:
        return [], {
            "status": "empty",
            "version": OPTIMIZER_VERSION,
            "mode": mode,
            "regime": regime,
            "processed": 0,
        }

    optimized: list[dict] = []
    stats = Counter()
    tier_changes = 0
    priority_changes = 0

    for original in recommendations:
        rec = dict(original)
        before_tier = str(rec.get("tier") or "C")
        before_priority = _safe_int(rec.get("priority_score"), 0)
        adjustments: list[str] = []
        priority_delta = 0

        news = _news_profile(rec, now)
        priority_delta += _apply_news_adjustment(rec, news, adjustments)
        priority_delta += _apply_regime_adjustment(rec, regime, adjustments)
        priority_delta += _apply_review_adjustment(
            rec,
            feedback_by_symbol.get(str(rec.get("symbol") or "")),
            adjustments,
        )

        if rec.get("chase_high_penalty") and rec.get("tier") == "A":
            rec["tier"] = "B"
            adjustments.append("追高惩罚禁止保留A档")

        after_priority = int(_clamp(before_priority + priority_delta, 0, 100))
        rec["priority_score"] = after_priority
        rec["news_freshness_score"] = news.get("freshness_score")
        rec["pool_optimizer"] = {
            "version": OPTIMIZER_VERSION,
            "mode": mode,
            "regime": regime,
            "regime_confidence": confidence,
            "tier_before": before_tier,
            "tier_after": rec.get("tier"),
            "priority_before": before_priority,
            "priority_after": after_priority,
            "priority_delta": after_priority - before_priority,
            "industry_key": _industry_key(rec),
            "news": news,
            "adjustments": adjustments,
        }
        rec["optimizer_adjustments"] = adjustments

        if rec.get("tier") != before_tier:
            tier_changes += 1
        if after_priority != before_priority:
            priority_changes += 1
        if news.get("has_news"):
            stats["with_news"] += 1
            stats[f"news_{news.get('direction')}"] += 1
            if _safe_float(news.get("freshness_score")) >= 0.65:
                stats["fresh_news"] += 1
            else:
                stats["stale_news"] += 1
        if rec.get("review_feedback"):
            stats["review_covered"] += 1
        if adjustments:
            stats["adjusted"] += 1

        optimized.append(rec)

    summary = {
        "status": "ok",
        "version": OPTIMIZER_VERSION,
        "mode": mode,
        "regime": regime,
        "regime_confidence": confidence,
        "processed": len(optimized),
        "adjusted": stats["adjusted"],
        "tier_changes": tier_changes,
        "priority_changes": priority_changes,
        "news_quality": {
            "with_news": stats["with_news"],
            "positive": stats["news_positive"],
            "negative": stats["news_negative"],
            "neutral": stats["news_neutral"],
            "fresh": stats["fresh_news"],
            "stale": stats["stale_news"],
        },
        "review_feedback": {
            "covered": stats["review_covered"],
        },
        "generated_at": now.isoformat(),
    }

    optimized = _apply_diversification(optimized, summary=summary)
    return optimized, summary
