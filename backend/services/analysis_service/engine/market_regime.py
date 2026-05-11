from __future__ import annotations

import math
from datetime import date, datetime

from backend.services.analysis_service.engine.scoring_data import fetch_recent_kline


_DEFAULT_INDICES = {
    "000300.SH": "HS300",
    "000905.SH": "CSI500",
    "399006.SZ": "ChiNext",
}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_float(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _pct_change(current: float, previous: float) -> float:
    return (current - previous) / previous * 100 if previous else 0.0


def _volume_ratio(rows: list[dict]) -> float | None:
    recent = [_safe_float(item.get("turnover") or item.get("volume")) for item in rows[-5:]]
    previous = [_safe_float(item.get("turnover") or item.get("volume")) for item in rows[-20:-5]]
    recent_values = [value for value in recent if value and value > 0]
    previous_values = [value for value in previous if value and value > 0]
    if len(recent_values) < 3 or len(previous_values) < 5:
        return None
    return _mean(recent_values) / _mean(previous_values)


def _signal(indicator: str, value: str, detail: str) -> dict:
    return {"indicator": indicator, "value": value, "detail": detail}


def _analyze_index(label: str, rows: list[dict]) -> dict | None:
    closes = [_safe_float(item.get("close")) for item in rows if item.get("close") is not None]
    closes = [value for value in closes if value is not None and value > 0]
    if len(closes) < 20:
        return None

    last_close = closes[-1]
    ma20 = _mean(closes[-20:])
    ma60 = _mean(closes[-60:]) if len(closes) >= 60 else ma20
    ret5 = _pct_change(last_close, closes[-5]) if len(closes) >= 5 else 0.0
    ret20 = _pct_change(last_close, closes[-20])
    high_window = max(closes[-60:]) if len(closes) >= 60 else max(closes)
    low_window = min(closes[-60:]) if len(closes) >= 60 else min(closes)

    trend_score = 0
    trend_value = "neutral"
    if last_close >= ma20 >= ma60 and ret20 > 0:
        trend_score = 2
        trend_value = "bullish"
    elif last_close >= ma20 and ret20 >= -3:
        trend_score = 1
        trend_value = "constructive"
    elif last_close < ma20 and ma20 <= ma60 and ret20 < 0:
        trend_score = -2
        trend_value = "bearish"
    elif last_close < ma20 or ret20 < -8:
        trend_score = -1
        trend_value = "weak"

    high_low_value = "neutral"
    if high_window and last_close >= high_window * 0.98:
        high_low_value = "near_high"
    elif low_window and last_close <= low_window * 1.02:
        high_low_value = "near_low"

    return {
        "label": label,
        "trend_value": trend_value,
        "trend_score": trend_score,
        "last_close": last_close,
        "ma20": ma20,
        "ma60": ma60,
        "ret5": ret5,
        "ret20": ret20,
        "volume_ratio": _volume_ratio(rows),
        "high_low_value": high_low_value,
    }


def _classify_regime(states: list[dict]) -> tuple[str, str, dict]:
    sampled = len(states)
    trend_score = sum(int(item["trend_score"]) for item in states)
    bullish = sum(1 for item in states if int(item["trend_score"]) > 0)
    bearish = sum(1 for item in states if int(item["trend_score"]) < 0)
    near_high = sum(1 for item in states if item.get("high_low_value") == "near_high")
    near_low = sum(1 for item in states if item.get("high_low_value") == "near_low")
    valid_volumes = [item["volume_ratio"] for item in states if item.get("volume_ratio")]
    avg_volume_ratio = _mean(valid_volumes) if valid_volumes else None

    breadth_ratio = bullish / sampled if sampled else 0.0
    weak_ratio = bearish / sampled if sampled else 0.0
    if breadth_ratio >= 0.67:
        breadth = "broad_positive"
    elif weak_ratio >= 0.67:
        breadth = "broad_negative"
    else:
        breadth = "mixed"

    volume = "unknown"
    if avg_volume_ratio is not None:
        if avg_volume_ratio >= 1.12 and trend_score > 0:
            volume = "confirming_risk_on"
        elif avg_volume_ratio >= 1.12 and trend_score < 0:
            volume = "confirming_risk_off"
        elif avg_volume_ratio <= 0.82:
            volume = "contracting"
        else:
            volume = "neutral"

    by_label = {item["label"]: item for item in states}
    hs300 = by_label.get("HS300")
    chinext = by_label.get("ChiNext")
    risk_spread = None
    risk_appetite = "unknown"
    if hs300 and chinext:
        risk_spread = float(chinext["ret20"]) - float(hs300["ret20"])
        if risk_spread >= 3:
            risk_appetite = "growth_risk_on"
        elif risk_spread <= -3:
            risk_appetite = "defensive_large_cap"
        else:
            risk_appetite = "neutral"

    if trend_score >= 4 and breadth == "broad_positive":
        regime = "strong_trend"
        confidence = "high" if sampled >= 3 and near_high >= 1 else "medium"
    elif trend_score <= -4 and breadth == "broad_negative":
        regime = "weak_market"
        confidence = "high" if sampled >= 3 and near_low >= 1 else "medium"
    elif trend_score >= 3 and volume == "confirming_risk_on":
        regime = "strong_trend"
        confidence = "medium"
    elif trend_score <= -3 and volume == "confirming_risk_off":
        regime = "weak_market"
        confidence = "medium"
    else:
        regime = "range_bound"
        confidence = "medium" if sampled >= 2 else "low"

    if regime == "strong_trend" and risk_appetite == "defensive_large_cap":
        confidence = "medium"
    elif regime == "weak_market" and risk_appetite == "growth_risk_on":
        confidence = "medium"
    elif regime != "range_bound" and breadth == "mixed":
        confidence = "medium"

    components = {
        "trend_score": trend_score,
        "breadth": breadth,
        "bullish_indices": bullish,
        "bearish_indices": bearish,
        "volume": volume,
        "volume_ratio": round(avg_volume_ratio, 4) if avg_volume_ratio is not None else None,
        "risk_appetite": risk_appetite,
        "risk_spread": round(risk_spread, 4) if risk_spread is not None else None,
    }
    return regime, confidence, components


def _suggested_strategies(regime: str, components: dict) -> list[str]:
    if regime == "strong_trend":
        if components.get("risk_appetite") == "growth_risk_on":
            return ["growth_momentum", "event_driven", "retail_small"]
        return ["growth_momentum", "event_driven"]
    if regime == "weak_market":
        return ["value_quality", "dividend_defensive", "reversal_watch"]
    return ["retail_small", "value_quality"]


async def detect_market_regime(as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    signals: list[dict] = []
    data_warnings: list[str] = []
    index_states: list[dict] = []

    for symbol, label in _DEFAULT_INDICES.items():
        try:
            kline = await fetch_recent_kline(symbol, 60)
        except Exception as exc:
            data_warnings.append(f"{label} data unavailable: {exc}")
            continue

        state = _analyze_index(label, kline)
        if not state:
            data_warnings.append(f"{label} has fewer than 20 usable kline rows")
            continue

        index_states.append(state)
        signals.append(
            _signal(
                f"{label}_trend",
                state["trend_value"],
                (
                    f"{label} close {state['last_close']:.2f}, MA20 {state['ma20']:.2f}, "
                    f"MA60 {state['ma60']:.2f}, ret5 {state['ret5']:+.1f}%, ret20 {state['ret20']:+.1f}%"
                ),
            )
        )

    sampled = len(index_states)
    if sampled == 0:
        regime = "range_bound"
        confidence = "low"
        components = {
            "trend_score": 0,
            "breadth": "unknown",
            "bullish_indices": 0,
            "bearish_indices": 0,
            "volume": "unknown",
            "volume_ratio": None,
            "risk_appetite": "unknown",
            "risk_spread": None,
        }
    else:
        regime, confidence, components = _classify_regime(index_states)
        signals.append(
            _signal(
                "market_breadth_proxy",
                str(components["breadth"]),
                (
                    f"{components['bullish_indices']}/{sampled} indices constructive, "
                    f"{components['bearish_indices']}/{sampled} weak"
                ),
            )
        )
        signals.append(
            _signal(
                "volume_confirmation",
                str(components["volume"]),
                (
                    f"recent 5-day volume/turnover vs prior 15-day average: {components['volume_ratio']:.2f}x"
                    if components.get("volume_ratio") is not None
                    else "volume/turnover data unavailable"
                ),
            )
        )
        signals.append(
            _signal(
                "risk_appetite_proxy",
                str(components["risk_appetite"]),
                (
                    f"ChiNext 20d return minus HS300 20d return: {components['risk_spread']:+.1f}%"
                    if components.get("risk_spread") is not None
                    else "risk appetite proxy unavailable"
                ),
            )
        )

    return {
        "regime": regime,
        "confidence": confidence,
        "signals": signals,
        "components": components,
        "suggested_strategies": _suggested_strategies(regime, components),
        "data_quality": {
            "sampled_indices": sampled,
            "warnings": data_warnings,
        },
        "updated_at": datetime.now().isoformat(),
        "as_of": as_of.isoformat(),
    }
