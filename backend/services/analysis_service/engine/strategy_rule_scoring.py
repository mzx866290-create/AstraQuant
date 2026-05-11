from __future__ import annotations

import math
from typing import Any

from backend.services.analysis_service.engine.strategy_config import load_strategy


DEFAULT_SCORING_RULES = {
    "retail_affordability": {
        "label": "single_lot_cost",
        "value": "price",
        "items": [
            {"max": 0, "delta": -25, "bucket": "missing", "message": "price unavailable"},
            {"min": 0, "max": 3, "delta": -16, "bucket": "too_low", "message": "price below 3"},
            {"min": 5, "max": 35, "delta": 14, "bucket": "ideal", "message": "single lot cost friendly"},
            {"min": 35, "max": 60, "delta": 6, "bucket": "acceptable", "message": "single lot cost acceptable"},
            {"min": 80, "delta": -18, "bucket": "too_high", "message": "single lot cost high"},
            {"delta": 0, "bucket": "neutral", "message": "price neutral"},
        ],
    },
    "market_cap": {
        "label": "market_cap",
        "value": "market_cap_yi",
        "missing": {"delta": -3, "bucket": "missing", "message": "market cap missing"},
        "items": [
            {"min": 30, "max": 500, "delta": 10, "bucket": "ideal", "message": "small/mid cap range"},
            {"max": 20, "delta": -8, "bucket": "too_small", "message": "market cap too small"},
            {"min": 1500, "delta": -14, "bucket": "too_large", "message": "market cap too large"},
            {"delta": 0, "bucket": "neutral", "message": "market cap neutral"},
        ],
    },
    "valuation": {
        "label": "valuation",
        "value": "valuation",
        "missing": {"delta": -4, "bucket": "missing", "message": "PE/PB missing"},
        "items": [
            {"pe_min": 0, "pe_max": 35, "pb_max": 5, "delta": 10, "bucket": "reasonable", "message": "PE/PB reasonable"},
            {"pe_max": 0, "delta": -8, "bucket": "abnormal", "message": "PE abnormal"},
            {"pe_min": 80, "delta": -8, "bucket": "expensive", "message": "PE too high"},
            {"pb_min": 10, "delta": -8, "bucket": "expensive", "message": "PB too high"},
            {"delta": 0, "bucket": "neutral", "message": "valuation neutral"},
        ],
    },
    "data_quality": {
        "label": "data_quality",
        "value": "data_grade",
        "items": [
            {"value": "A", "delta": 12, "bucket": "complete", "message": "data complete enough for deeper research"},
            {
                "value": "B",
                "delta": 7,
                "bucket": "partial",
                "message": "market/kline data available with partial fundamental or sentiment context",
            },
            {
                "value": "C",
                "delta": 2,
                "bucket": "basic",
                "status": "warning",
                "message": "basic quote and kline data available, but fundamentals are incomplete",
            },
            {
                "value": "D",
                "delta": 0,
                "bucket": "insufficient",
                "status": "warning",
                "message": "data completeness is insufficient",
            },
        ],
    },
    "technical": {
        "label": "technical",
        "value": "technical",
        "items": [
            {
                "bucket": "stable",
                "ret5_min": -3,
                "ret5_max": 12,
                "ret20_min": -8,
                "delta": 13,
                "message": "technical trend is stable",
            },
            {
                "bucket": "overextended",
                "ret5_min": 18,
                "delta": -8,
                "message": "short-term gain is too fast; chase risk is elevated",
            },
            {"bucket": "weak", "ret20_max": -15, "delta": -6, "message": "20-day trend is weak"},
            {"bucket": "neutral", "delta": 0, "message": "technical trend is neutral"},
        ],
        "insufficient": {
            "delta": 0,
            "bucket": "insufficient",
            "status": "warning",
            "message": "kline history has fewer than 20 bars; technical trend not scored",
        },
    },
    "volume": {
        "label": "volume",
        "value": "volume",
        "items": [
            {
                "bucket": "moderate_improvement",
                "ratio_min": 1.15,
                "ratio_max": 2.8,
                "delta": 5,
                "message": "recent 5-day trading activity improved moderately",
            },
            {"bucket": "neutral", "delta": 0, "message": "trading activity is neutral"},
        ],
        "insufficient": {
            "delta": 0,
            "bucket": "insufficient",
            "status": "warning",
            "message": "volume history has fewer than 10 bars; volume not scored",
        },
    },
    "financial_quality": {
        "label": "financial_quality",
        "value": "financial_quality",
        "missing": {"key": "financial", "delta": -5, "bucket": "missing", "message": "financial data missing"},
        "items": [
            {
                "key": "financial_revenue",
                "label": "financial",
                "metric": "revenue_yoy",
                "operator": "gt",
                "threshold": 0,
                "delta": 4,
                "bucket": "revenue_positive",
                "message": "revenue yoy is positive",
            },
            {
                "key": "financial_profit",
                "label": "financial",
                "metric": "net_profit_yoy",
                "operator": "gt",
                "threshold": 0,
                "delta": 6,
                "bucket": "profit_positive",
                "message": "net profit yoy is positive",
            },
            {
                "key": "financial_cashflow",
                "label": "cashflow",
                "metric": "operating_cf",
                "operator": "lt",
                "threshold": 0,
                "delta": -5,
                "bucket": "cashflow_negative",
                "message": "operating cash flow is negative",
            },
        ],
    },
}


def configured_rule_result(stock_data: dict[str, Any], strategy_id: str, factor: str) -> dict[str, Any] | None:
    rules = _strategy_rules(strategy_id)
    rule = rules.get(factor)
    if not isinstance(rule, dict):
        return None
    return evaluate_rule(stock_data, factor, rule)


def evaluate_rule(stock_data: dict[str, Any], factor: str, rule: dict[str, Any]) -> dict[str, Any]:
    if factor == "valuation" or rule.get("value") == "valuation":
        return _evaluate_valuation_rule(stock_data, factor, rule)
    if factor == "technical" or rule.get("value") == "technical":
        return _evaluate_technical_rule(stock_data, factor, rule)
    if factor == "volume" or rule.get("value") == "volume":
        return _evaluate_volume_rule(stock_data, factor, rule)
    if factor == "financial_quality" or rule.get("value") == "financial_quality":
        return _evaluate_financial_quality_rule(stock_data, factor, rule)
    default_rule = DEFAULT_SCORING_RULES.get(factor, {})
    value_name = str(rule.get("value") or default_rule.get("value") or factor)
    value = _factor_value(stock_data, value_name)
    if value is None:
        missing = _missing_item(rule)
        if missing:
            return _result(factor, rule, missing, value)
    for item in _rule_ranges(rule):
        if not isinstance(item, dict):
            continue
        item_value = item.get("value")
        if item_value == "missing":
            continue
        if item_value not in (None, "otherwise", "default") and not _value_matches(value, item_value):
            continue
        if _range_matches(value, item):
            return _result(factor, rule, item, value)
    return _result(factor, rule, {"delta": 0, "bucket": "neutral", "message": f"{factor} neutral"}, value)


def _evaluate_valuation_rule(stock_data: dict[str, Any], factor: str, rule: dict[str, Any]) -> dict[str, Any]:
    quote = stock_data.get("quote") or {}
    financial = stock_data.get("financial") or {}
    pe = _safe_float(financial.get("pe_ttm") or quote.get("pe_ttm"))
    pb = _safe_float(financial.get("pb") or quote.get("pb"))
    if pe is None or pb is None or pe == 0 or pb == 0:
        missing = _missing_item(rule)
        return _result(factor, rule, missing or {"delta": -4, "bucket": "missing", "message": "PE/PB missing"}, None)
    for item in _rule_ranges(rule):
        if not isinstance(item, dict):
            continue
        selector = item.get("value")
        if selector and selector not in ("otherwise", "default"):
            continue
        if _valuation_matches(pe, pb, item):
            result = _result(factor, rule, item, {"pe": pe, "pb": pb})
            result["pe"] = pe
            result["pb"] = pb
            return result
    result = _result(factor, rule, {"delta": 0, "bucket": "neutral", "message": "valuation neutral"}, {"pe": pe, "pb": pb})
    result["pe"] = pe
    result["pb"] = pb
    return result


def _evaluate_technical_rule(stock_data: dict[str, Any], factor: str, rule: dict[str, Any]) -> dict[str, Any]:
    closes = [
        value
        for value in (_safe_float(item.get("close")) for item in stock_data.get("kline_data") or [])
        if value is not None
    ]
    close_window = int(_safe_float(rule.get("close_window")) or 20)
    if len(closes) < close_window:
        insufficient = rule.get("insufficient") if isinstance(rule.get("insufficient"), dict) else None
        return _result(factor, rule, insufficient or {"delta": 0, "bucket": "insufficient", "status": "warning"}, None)

    metrics = _technical_metrics(closes)
    for item in _technical_items(rule):
        if _technical_matches(metrics, item):
            result = _result(factor, rule, item, metrics)
            result.update(metrics)
            return result
    result = _result(factor, rule, {"delta": 0, "bucket": "neutral", "message": "technical trend is neutral"}, metrics)
    result.update(metrics)
    return result


def _evaluate_volume_rule(stock_data: dict[str, Any], factor: str, rule: dict[str, Any]) -> dict[str, Any]:
    volumes = [
        value
        for value in (_safe_float(item.get("volume")) for item in stock_data.get("kline_data") or [])
        if value is not None
    ]
    volume_window = int(_safe_float(rule.get("volume_window")) or 10)
    if len(volumes) < volume_window:
        insufficient = rule.get("insufficient") if isinstance(rule.get("insufficient"), dict) else None
        return _result(factor, rule, insufficient or {"delta": 0, "bucket": "insufficient", "status": "warning"}, None)

    metrics = _volume_metrics(volumes)
    for item in _rule_ranges(rule):
        if _volume_matches(metrics, item):
            result = _result(factor, rule, item, metrics)
            result.update(metrics)
            return result
    result = _result(factor, rule, {"delta": 0, "bucket": "neutral", "message": "trading activity is neutral"}, metrics)
    result.update(metrics)
    return result


def _evaluate_financial_quality_rule(stock_data: dict[str, Any], factor: str, rule: dict[str, Any]) -> dict[str, Any]:
    financial = stock_data.get("financial") or {}
    if not financial:
        missing = _missing_item(rule)
        component = _result(
            factor,
            rule,
            missing or {"key": "financial", "delta": -5, "bucket": "missing", "message": "financial data missing"},
            None,
        )
        component["key"] = (missing or {}).get("key") or "financial"
        return _aggregate_components(factor, rule, [component])

    components: list[dict[str, Any]] = []
    for item in _rule_ranges(rule):
        metric = item.get("metric")
        if not metric:
            continue
        value = _safe_float(financial.get(str(metric)))
        threshold = _safe_float(item.get("threshold"))
        if value is None or threshold is None:
            continue
        if _operator_matches(value, str(item.get("operator") or "gt"), threshold):
            component = _result(factor, rule, item, value)
            component["key"] = item.get("key") or factor
            component["label"] = item.get("label") or rule.get("label") or factor
            component["metric"] = metric
            component["threshold"] = threshold
            components.append(component)
    return _aggregate_components(factor, rule, components)


def _aggregate_components(factor: str, rule: dict[str, Any], components: list[dict[str, Any]]) -> dict[str, Any]:
    delta = sum(int(item.get("delta") or 0) for item in components)
    return {
        "key": factor,
        "label": rule.get("label") or factor,
        "delta": delta,
        "status": "positive" if delta > 0 else "negative" if delta < 0 else "neutral",
        "message": rule.get("message") or f"{factor}: {len(components)} matched components",
        "bucket": "component_sum",
        "value": None,
        "components": components,
    }


def _strategy_rules(strategy_id: str) -> dict[str, Any]:
    try:
        strategy = load_strategy(strategy_id)
    except Exception:
        strategy = {}
    configured = strategy.get("scoring_rules") if isinstance(strategy.get("scoring_rules"), dict) else {}
    rules = {key: dict(value) for key, value in DEFAULT_SCORING_RULES.items()}
    for key, value in configured.items():
        if isinstance(value, dict):
            merged = dict(rules.get(key, {}))
            merged.update(value)
            rules[key] = merged
    return rules


def _rule_ranges(rule: dict[str, Any]) -> list[dict[str, Any]]:
    ranges = rule.get("ranges")
    if isinstance(ranges, list):
        return [item for item in ranges if isinstance(item, dict)]
    items = rule.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _technical_items(rule: dict[str, Any]) -> list[dict[str, Any]]:
    items = _rule_ranges(rule)
    if items:
        return items
    result: list[dict[str, Any]] = []
    for bucket in ("stable", "overextended", "weak", "default"):
        value = rule.get(bucket)
        if not isinstance(value, dict):
            continue
        item = dict(value)
        item.setdefault("bucket", "neutral" if bucket == "default" else bucket)
        if bucket == "default":
            item.setdefault("message", "technical trend is neutral")
        result.append(item)
    return result


def _missing_item(rule: dict[str, Any]) -> dict[str, Any] | None:
    missing = rule.get("missing")
    if isinstance(missing, dict):
        return missing
    items = rule.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and str(item.get("value") or "").startswith("missing"):
            return item
    return None


def _factor_value(stock_data: dict[str, Any], name: str) -> float | None:
    quote = stock_data.get("quote") or {}
    financial = stock_data.get("financial") or {}
    readiness = stock_data.get("readiness") or {}
    if name == "data_grade":
        return ((readiness.get("data_grade") or {}).get("grade") or "D").upper()
    if name == "price":
        value = _safe_float(stock_data.get("price"))
        return value if value is not None else 0.0
    if name == "market_cap_yi":
        mv = _safe_float(financial.get("total_mv") or quote.get("total_mv"))
        if mv is None:
            mv = _safe_float(financial.get("circ_mv") or quote.get("circ_mv"))
        return mv / 1e8 if mv is not None and mv > 0 else None
    return _safe_float(stock_data.get(name) or financial.get(name) or quote.get(name))


def _value_matches(actual: Any, expected: Any) -> bool:
    if actual is None:
        return False
    return str(actual).strip().upper() == str(expected).strip().upper()


def _technical_metrics(closes: list[float]) -> dict[str, float]:
    ma_window = min(20, len(closes))
    return {
        "close": closes[-1],
        "ma20": sum(closes[-ma_window:]) / ma_window,
        "ret5": _window_return(closes, 5),
        "ret20": _window_return(closes, 20),
    }


def _volume_metrics(volumes: list[float]) -> dict[str, float]:
    previous_avg = sum(volumes[-10:-5]) / 5 if len(volumes) >= 10 else 0.0
    recent_avg = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0.0
    return {
        "ratio": recent_avg / previous_avg if previous_avg else 0.0,
        "recent_avg": recent_avg,
        "previous_avg": previous_avg,
    }


def _window_return(values: list[float], window: int) -> float:
    if len(values) < window or not values[-window]:
        return 0.0
    return (values[-1] - values[-window]) / values[-window] * 100


def _technical_matches(metrics: dict[str, float], item: dict[str, Any]) -> bool:
    if item.get("bucket") == "stable" and metrics["close"] < metrics["ma20"]:
        return False
    return _metric_checks_match(
        metrics,
        item,
        (
            ("ret5_min", "ret5", "min"),
            ("ret5_max", "ret5", "max"),
            ("ret20_min", "ret20", "min"),
            ("ret20_max", "ret20", "max"),
        ),
    )


def _volume_matches(metrics: dict[str, float], item: dict[str, Any]) -> bool:
    return _metric_checks_match(metrics, item, (("ratio_min", "ratio", "min"), ("ratio_max", "ratio", "max")))


def _metric_checks_match(
    metrics: dict[str, float],
    item: dict[str, Any],
    checks: tuple[tuple[str, str, str], ...],
) -> bool:
    if not any(config_key in item for config_key, _metric_key, _kind in checks):
        return True
    for config_key, metric_key, kind in checks:
        if config_key not in item:
            continue
        threshold = _safe_float(item.get(config_key))
        if threshold is None:
            continue
        value = metrics.get(metric_key, 0.0)
        if kind == "min" and value < threshold:
            return False
        if kind == "max" and value > threshold:
            return False
    return True


def _operator_matches(value: float, operator: str, threshold: float) -> bool:
    if operator == "gte":
        return value >= threshold
    if operator == "lt":
        return value < threshold
    if operator == "lte":
        return value <= threshold
    return value > threshold


def _range_matches(value: float | None, item: dict[str, Any]) -> bool:
    if "min" not in item and "max" not in item:
        return True
    if value is None:
        return False
    numeric_value = _safe_float(value)
    if numeric_value is None:
        return False
    low = _safe_float(item.get("min")) if "min" in item else None
    high = _safe_float(item.get("max")) if "max" in item else None
    if low is not None and numeric_value < low:
        return False
    if high is not None and numeric_value > high:
        return False
    return True


def _valuation_matches(pe: float, pb: float, item: dict[str, Any]) -> bool:
    keys = ("pe_min", "pe_max", "pb_min", "pb_max")
    if not any(key in item for key in keys):
        return True
    pe_min = _safe_float(item.get("pe_min", item.get("min"))) if "pe_min" in item or "min" in item else None
    pe_max = _safe_float(item.get("pe_max", item.get("max"))) if "pe_max" in item or "max" in item else None
    pb_min = _safe_float(item.get("pb_min")) if "pb_min" in item else None
    pb_max = _safe_float(item.get("pb_max")) if "pb_max" in item else None
    if pe_min is not None and pe <= pe_min:
        return False
    if pe_max is not None and pe > pe_max:
        return False
    if pb_min is not None and pb <= pb_min:
        return False
    if pb_max is not None and pb > pb_max:
        return False
    return True


def _result(factor: str, rule: dict[str, Any], item: dict[str, Any], value: Any) -> dict[str, Any]:
    delta = int(_safe_float(item.get("delta")) or 0)
    return {
        "key": factor,
        "label": rule.get("label") or factor,
        "delta": delta,
        "status": item.get("status") or ("positive" if delta > 0 else "negative" if delta < 0 else "neutral"),
        "message": item.get("message") or f"{factor}: {item.get('bucket') or 'matched'}",
        "bucket": item.get("bucket"),
        "value": value,
    }


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None
