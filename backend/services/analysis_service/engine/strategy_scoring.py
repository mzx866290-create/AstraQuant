from __future__ import annotations

import math
from typing import Any

from backend.services.analysis_service.engine.strategy_config import _normalize_weights


_FACTOR_ALIASES = {
    "financial": "financial_quality",
    "financial_revenue": "financial_quality",
    "financial_profit": "financial_quality",
    "financial_cashflow": "financial_quality",
    "news_sentiment": "sentiment",
    "industry_events": "industry_theme",
    "theme_validation": "industry_theme",
    "volume": "technical",
    "risk_lights": "risk",
}

_DEFAULT_SCORE_BLENDING = {
    "base_weight": 0.65,
    "weighted_weight": 0.35,
    "multiplier_min": 0.35,
    "multiplier_max": 2.25,
    "anchor": None,
}


def strategy_factor_key(factor: str, weights: dict[str, float]) -> str | None:
    normalized = str(factor or "").strip()
    if not normalized:
        return None
    if normalized in weights:
        return normalized
    aliased = _FACTOR_ALIASES.get(normalized)
    if aliased in weights:
        return aliased
    if normalized.startswith("risk_") and "risk" in weights:
        return "risk"
    return None


def apply_strategy_weighted_score(item: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    """Add a conservative strategy-weighted score while preserving the original score."""

    marked = dict(item)
    base_score = _safe_score(marked.get("score"))
    weights = _normalize_weights(strategy.get("weights"))
    blending = _score_blending(strategy.get("score_blending"))
    breakdown = list(marked.get("score_breakdown") or [])
    if base_score is None or not weights or not breakdown:
        marked.setdefault("base_score", base_score)
        marked.setdefault("strategy_score", base_score)
        marked.setdefault("strategy_score_delta", 0)
        marked.setdefault("strategy_weighted_factors", [])
        marked.setdefault("strategy_score_blending", blending)
        return marked

    neutral_weight = 1.0 / max(len(weights), 1)
    anchor = blending["anchor"] if blending["anchor"] is not None else 50.0
    weighted_delta_total = 0.0
    factors: list[dict[str, Any]] = []

    for entry in breakdown:
        factor = str(entry.get("key") or "")
        delta = _safe_float(entry.get("delta"))
        if delta is None:
            continue
        if factor == "base":
            if blending["anchor"] is None:
                anchor = delta
            continue

        dimension = strategy_factor_key(factor, weights)
        weight = weights.get(dimension) if dimension else None
        multiplier = _factor_multiplier(weight, neutral_weight, blending)
        weighted_delta = delta * multiplier
        weighted_delta_total += weighted_delta
        factors.append(
            {
                "factor": factor,
                "dimension": dimension or "unmapped",
                "delta": delta,
                "weight": round(float(weight), 6) if weight is not None else None,
                "neutral_weight": round(neutral_weight, 6),
                "multiplier": round(multiplier, 4),
                "weighted_delta": round(weighted_delta, 2),
                "label": entry.get("label"),
            }
        )

    weighted_score = _clamp_score(anchor + weighted_delta_total)
    strategy_score = _clamp_score(base_score * blending["base_weight"] + weighted_score * blending["weighted_weight"])
    marked["base_score"] = int(round(base_score))
    marked["strategy_score"] = strategy_score
    marked["strategy_score_delta"] = strategy_score - int(round(base_score))
    marked["strategy_score_blending"] = blending
    marked["strategy_weighted_factors"] = sorted(
        factors,
        key=lambda row: abs(float(row.get("weighted_delta") or 0)),
        reverse=True,
    )
    marked["score"] = strategy_score
    return marked


def _score_blending(config: Any) -> dict[str, float | None]:
    if not isinstance(config, dict):
        config = {}

    base_weight = _safe_float(config.get("base_weight"))
    weighted_weight = _safe_float(config.get("weighted_weight"))
    if base_weight is None or base_weight < 0:
        base_weight = float(_DEFAULT_SCORE_BLENDING["base_weight"])
    if weighted_weight is None or weighted_weight < 0:
        weighted_weight = float(_DEFAULT_SCORE_BLENDING["weighted_weight"])
    total_weight = base_weight + weighted_weight
    if total_weight <= 0:
        base_weight = float(_DEFAULT_SCORE_BLENDING["base_weight"])
        weighted_weight = float(_DEFAULT_SCORE_BLENDING["weighted_weight"])
    else:
        base_weight = base_weight / total_weight
        weighted_weight = weighted_weight / total_weight

    multiplier_min = _safe_float(config.get("multiplier_min"))
    multiplier_max = _safe_float(config.get("multiplier_max"))
    if multiplier_min is None or multiplier_min < 0:
        multiplier_min = float(_DEFAULT_SCORE_BLENDING["multiplier_min"])
    if multiplier_max is None or multiplier_max <= 0:
        multiplier_max = float(_DEFAULT_SCORE_BLENDING["multiplier_max"])
    if multiplier_min > multiplier_max:
        multiplier_min, multiplier_max = multiplier_max, multiplier_min

    return {
        "base_weight": round(base_weight, 6),
        "weighted_weight": round(weighted_weight, 6),
        "multiplier_min": round(multiplier_min, 6),
        "multiplier_max": round(multiplier_max, 6),
        "anchor": _safe_float(config.get("anchor")),
    }


def _factor_multiplier(weight: float | None, neutral_weight: float, blending: dict[str, float | None] | None = None) -> float:
    if weight is None or neutral_weight <= 0:
        return 1.0
    blending = blending or _score_blending(None)
    ratio = float(weight) / neutral_weight
    if ratio >= 1:
        return min(float(blending["multiplier_max"]), ratio)
    return max(float(blending["multiplier_min"]), ratio)


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _safe_score(value: Any) -> float | None:
    score = _safe_float(value)
    if score is None:
        return None
    return max(0.0, min(100.0, score))


def _clamp_score(value: float) -> int:
    return int(max(0, min(100, round(value))))
