from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "strategies"
_DEFAULT_STRATEGY = "retail_small"
_AUTO_STRATEGY = "auto"
_ALIASES = {
    "quality": "value_quality",
}


def _normalize_weights(weights: dict | None) -> dict[str, float]:
    if not isinstance(weights, dict):
        return {}
    clean: dict[str, float] = {}
    for key, value in weights.items():
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        clean[str(key)] = max(0.0, min(1.0, weight))
    total = sum(clean.values())
    if total <= 0:
        return clean
    return {key: round(value / total, 6) for key, value in clean.items()}


@lru_cache(maxsize=1)
def _load_all_strategies() -> dict[str, dict]:
    strategies: dict[str, dict] = {}
    for path in sorted(_CONFIG_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        strategy_id = str(payload.get("id") or path.stem).strip()
        if not strategy_id:
            continue
        payload["id"] = strategy_id
        payload.setdefault("name", strategy_id)
        payload.setdefault("engine_strategy", "quality")
        payload.setdefault("preferred_regimes", [])
        payload.setdefault("filters", {})
        payload.setdefault("score_threshold", 55)
        payload["weights"] = _normalize_weights(payload.get("weights"))
        strategies[strategy_id] = payload
    if _DEFAULT_STRATEGY not in strategies:
        raise RuntimeError(f"default strategy {_DEFAULT_STRATEGY!r} is missing")
    return strategies


def list_strategy_ids(include_auto: bool = True) -> list[str]:
    ids = list(_load_all_strategies().keys())
    return [_AUTO_STRATEGY, *ids] if include_auto else ids


def load_strategy(strategy_id: str) -> dict:
    normalized = (strategy_id or _DEFAULT_STRATEGY).strip().lower()
    normalized = _ALIASES.get(normalized, normalized)
    if normalized == _AUTO_STRATEGY:
        return {
            "id": _AUTO_STRATEGY,
            "name": "自动策略",
            "description": "根据市场环境自动选择策略。",
            "engine_strategy": _DEFAULT_STRATEGY,
            "preferred_regimes": [],
            "filters": {},
            "score_threshold": 55,
        }
    strategies = _load_all_strategies()
    if normalized not in strategies:
        raise KeyError(normalized)
    return dict(strategies[normalized])


def resolve_strategy(requested: str, market_regime: dict | None = None) -> dict:
    normalized = (requested or _AUTO_STRATEGY).strip().lower()
    normalized = _ALIASES.get(normalized, normalized)
    if normalized and normalized != _AUTO_STRATEGY:
        strategy = load_strategy(normalized)
        strategy["selection_mode"] = "manual"
        return strategy

    regime_payload = market_regime or {}
    suggested = regime_payload.get("suggested_strategies") or []
    confidence = str(regime_payload.get("confidence") or "").lower()
    for candidate in suggested:
        if candidate in _load_all_strategies():
            strategy = load_strategy(candidate)
            strategy["selection_mode"] = "auto"
            strategy["selection_reason"] = f"market_regime:{regime_payload.get('regime') or 'unknown'}"
            return strategy

    fallback = load_strategy(_DEFAULT_STRATEGY)
    fallback["selection_mode"] = "auto"
    fallback["selection_reason"] = (
        "market_regime_low_confidence" if confidence in {"low", ""} else "market_regime_default_fallback"
    )
    return fallback
