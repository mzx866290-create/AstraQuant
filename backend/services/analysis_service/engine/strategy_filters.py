from __future__ import annotations

import math
from typing import Any


def evaluate_strategy_filters(item: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    filters = strategy.get("filters") if isinstance(strategy.get("filters"), dict) else {}
    hard: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    _check_range(
        hard,
        warnings,
        key="price_range",
        label="price",
        value=_safe_float(item.get("price")),
        bounds=filters.get("price_range"),
        hard_missing=False,
    )
    market_cap_yi = _safe_float(item.get("total_mv"))
    if market_cap_yi is not None:
        market_cap_yi = market_cap_yi / 1e8
    _check_range(
        hard,
        warnings,
        key="market_cap_range_yi",
        label="market_cap_yi",
        value=market_cap_yi,
        bounds=filters.get("market_cap_range_yi"),
        hard_missing=False,
    )

    threshold = _safe_float(strategy.get("score_threshold"))
    strategy_score = _safe_float(item.get("strategy_score", item.get("score")))
    if threshold is not None and strategy_score is not None and strategy_score < threshold:
        hard.append(
            {
                "type": "score_below_strategy_threshold",
                "severity": "hard",
                "detail": f"strategy score {strategy_score:.0f} below threshold {threshold:.0f}",
                "value": strategy_score,
                "threshold": threshold,
            }
        )

    passed = not hard
    return {
        "passed": passed,
        "level": "none" if passed and not warnings else "soft" if passed else "hard",
        "filters": filters,
        "hard": hard,
        "warnings": warnings,
    }


def append_strategy_filter_warnings(item: dict[str, Any], filter_result: dict[str, Any]) -> dict[str, Any]:
    if not filter_result.get("warnings"):
        return item
    marked = dict(item)
    warning_labels = [entry.get("detail") for entry in filter_result["warnings"] if entry.get("detail")]
    marked["risk_flags"] = list(dict.fromkeys([*(marked.get("risk_flags") or []), *warning_labels]))[:6]
    return marked


def _check_range(
    hard: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    *,
    key: str,
    label: str,
    value: float | None,
    bounds: Any,
    hard_missing: bool,
) -> None:
    if not _valid_bounds(bounds):
        return
    low, high = float(bounds[0]), float(bounds[1])
    if value is None:
        target = hard if hard_missing else warnings
        target.append(
            {
                "type": f"{key}_missing",
                "severity": "hard" if hard_missing else "soft",
                "detail": f"{label} missing for strategy filter",
                "value": None,
                "threshold": [low, high],
            }
        )
        return
    if value < low or value > high:
        hard.append(
            {
                "type": f"{key}_out_of_range",
                "severity": "hard",
                "detail": f"{label} {value:.2f} outside strategy range [{low:.2f}, {high:.2f}]",
                "value": value,
                "threshold": [low, high],
            }
        )


def _valid_bounds(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return False
    low = _safe_float(value[0])
    high = _safe_float(value[1])
    return low is not None and high is not None and low <= high


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None
