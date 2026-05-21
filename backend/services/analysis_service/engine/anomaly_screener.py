"""趋势筛选器 — 识别趋势向好、尚未过热、量价质量较好的观察池候选股"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import text

from backend.shared.database import SessionLocal

logger = logging.getLogger(__name__)

def _env_float(name: str, default: float, *, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


MIN_MARKET_CAP = _env_float("DAILY_POOL_MIN_MARKET_CAP_YI", 20.0, min_value=1.0) * 1e8
MAX_SINGLE_DAY_GAIN = _env_float("DAILY_POOL_MAX_SINGLE_DAY_GAIN", 9.0, min_value=3.0, max_value=20.0)
MAX_5D_GAIN = _env_float("DAILY_POOL_MAX_5D_GAIN", 15.0, min_value=5.0, max_value=40.0)
MAX_DISTANCE_MA20 = _env_float("DAILY_POOL_MAX_DISTANCE_MA20", 0.15, min_value=0.03, max_value=0.50)
MIN_TREND_R2 = _env_float("DAILY_POOL_MIN_TREND_R2", 0.30, min_value=0.05, max_value=0.90)
MIN_PULLBACK_20D_GAIN = _env_float("DAILY_POOL_MIN_PULLBACK_20D_GAIN", 6.0, min_value=0.0, max_value=30.0)
MIN_REVERSAL_5D_DROP = _env_float("DAILY_POOL_MIN_REVERSAL_5D_DROP", -10.0, min_value=-30.0, max_value=-3.0)

POOL_TREND = "trend_strength"
POOL_PULLBACK = "pullback_support"
POOL_REVERSAL = "oversold_reversal"


SNAPSHOT_COLUMNS = [
    "symbol", "name", "market", "open", "high", "low", "close",
    "prev_close", "change_pct", "volume", "turnover",
    "turnover_rate", "total_mv", "circ_mv",
    "vol_ratio_5d", "ma5", "ma20", "ma60",
]


HISTORY_COLUMNS = [
    "trade_date", "close", "prev_close", "change_pct", "volume",
    "turnover_rate", "ma5", "ma20", "ma60",
]


def screen_anomalies(trade_date: str, lookback_days: int = 5) -> list[dict]:
    """
    从 daily_snapshots 筛选趋势向好、尚未过热的观察池候选股。

    第一层确认趋势：MA 多头排列、20 日线性回归上行且拟合度足够、近 5 日未暴涨。
    第二层评估质量：量价配合、动量适中、波动收窄、换手适中、价格位置健康。
    """
    db = SessionLocal()
    try:
        candidates = _load_base_candidates(db, trade_date)
        history = _load_recent_history(db, trade_date, max(60, lookback_days + 20))

        results = []
        for item in candidates:
            hist = history.get(item["symbol"], [])
            evaluated = _evaluate_candidate(item, hist)
            if evaluated:
                results.append(evaluated)

        logger.info(
            "Trend-quality screener: %s candidates from %s base matches (date=%s)",
            len(results),
            len(candidates),
            trade_date,
        )
        return results
    finally:
        db.close()


def _load_base_candidates(db, trade_date: str) -> list[dict]:
    stmt = text("""
        SELECT
            s.symbol, s.name, s.market, s.open, s.high, s.low, s.close,
            s.prev_close, s.change_pct, s.volume, s.turnover,
            s.turnover_rate, s.total_mv, s.circ_mv,
            s.vol_ratio_5d, s.ma5, s.ma20, s.ma60
        FROM daily_snapshots s
        WHERE s.trade_date = :td
          AND s.volume > 0
          AND (s.total_mv IS NULL OR s.total_mv >= :min_mv)
          AND s.name NOT LIKE '%ST%'
          AND s.change_pct < :max_gain
          AND s.change_pct > -9.5
    """)
    rows = db.execute(stmt, {
        "td": trade_date,
        "min_mv": MIN_MARKET_CAP,
        "max_gain": MAX_SINGLE_DAY_GAIN,
    }).fetchall()
    return [dict(zip(SNAPSHOT_COLUMNS, row)) for row in rows]


def _evaluate_candidate(item: dict, hist: list[dict]) -> dict | None:
    close = item.get("close") or 0
    if not close:
        return None

    item = _fill_missing_technical_fields(item, hist, close)
    ma20 = item.get("ma20") or 0
    ma60 = item.get("ma60") or item.get("ma60_proxy") or 0
    ma5 = item.get("ma5") or 0

    if ma20 and ma5:
        distance_ma20 = (close - ma20) / ma20
    else:
        distance_ma20 = _short_history_distance(item, close, ma5)
        item["ma5"] = ma5 or close
        item["ma20"] = ma20 or (close / (1 + distance_ma20) if distance_ma20 > -0.95 else close)
        item["ma60_proxy"] = ma60 or item["ma20"] * 0.98
        item["technical_fallback"] = "insufficient_snapshot_history"

    recent_5d_gain = _period_return(hist, 5, close)
    if recent_5d_gain is None:
        recent_5d_gain = item.get("change_pct") or 0

    closes_20 = [close] + [h["close"] for h in hist[:19] if h.get("close")]
    trend = _linear_regression(closes_20)
    if not trend:
        trend = {
            "slope_pct": max(0.01, (item.get("change_pct") or 0) / 5),
            "r2": 0.35,
            "fallback": "insufficient_snapshot_history",
        }

    quality = _build_quality_features(item, hist, close, distance_ma20, recent_5d_gain)
    bucket = _classify_observation_bucket(item, trend, quality, distance_ma20, recent_5d_gain)
    if not bucket:
        return None

    reasons = _build_reasons(item, trend, quality, distance_ma20, bucket)
    if not reasons:
        return None

    item["trend_features"] = {
        "slope_pct": round(trend["slope_pct"], 4),
        "r2": round(trend["r2"], 4),
        "recent_5d_gain": round(recent_5d_gain, 2),
        "distance_ma20": round(distance_ma20, 4),
    }
    item["quality_features"] = quality
    item["anomaly_reasons"] = reasons
    item["observation_bucket"] = bucket["id"]
    item["observation_bucket_label"] = bucket["label"]
    return item


def _classify_observation_bucket(
    item: dict,
    trend: dict,
    quality: dict,
    distance_ma20: float,
    recent_5d_gain: float,
) -> dict | None:
    close = item.get("close") or 0
    ma5 = item.get("ma5") or 0
    ma20 = item.get("ma20") or 0
    ma60 = item.get("ma60") or item.get("ma60_proxy") or 0
    change_pct = item.get("change_pct") or 0
    roc_20 = quality.get("roc_20d")
    vol_ratio = item.get("vol_ratio_5d") or 1.0
    trend_ok = trend.get("slope_pct", 0) > 0 and trend.get("r2", 0) >= MIN_TREND_R2
    ma_bullish = bool(close and ma5 and ma20 and ma60 and close > ma20 and ma5 >= ma20 and ma20 >= ma60)
    short_history = bool(item.get("technical_fallback"))

    if short_history:
        if -0.06 <= distance_ma20 <= 0.02 and recent_5d_gain <= 3 and -5.5 <= change_pct <= 1.5:
            return {"id": POOL_PULLBACK, "label": "回调承接"}
        if distance_ma20 < -0.06 and recent_5d_gain <= -6 and -8.5 <= change_pct <= 2.5:
            return {"id": POOL_REVERSAL, "label": "超跌反弹"}
        if -0.02 <= distance_ma20 <= MAX_DISTANCE_MA20 and recent_5d_gain <= MAX_5D_GAIN:
            return {"id": POOL_TREND, "label": "趋势强势"}
        return None

    if (
        ma20
        and ma60
        and close >= ma60
        and -0.06 <= distance_ma20 <= 0.05
        and recent_5d_gain <= 6
        and (roc_20 is None or roc_20 >= MIN_PULLBACK_20D_GAIN)
        and -5.5 <= change_pct <= 2.5
    ):
        return {"id": POOL_PULLBACK, "label": "回调承接"}

    if (
        ma20
        and distance_ma20 <= -0.03
        and recent_5d_gain <= min(MIN_REVERSAL_5D_DROP, -6.0)
        and -8.5 <= change_pct <= 4.0
        and 0.8 <= vol_ratio <= 3.5
    ):
        return {"id": POOL_REVERSAL, "label": "超跌反弹"}

    if (
        ma_bullish
        and trend_ok
        and 0 <= distance_ma20 <= MAX_DISTANCE_MA20
        and recent_5d_gain <= MAX_5D_GAIN
    ):
        return {"id": POOL_TREND, "label": "趋势强势"}

    return None


def _short_history_distance(item: dict, close: float, ma5: float) -> float:
    if ma5:
        return (close - ma5) / ma5
    change_pct = item.get("change_pct") or 0
    return change_pct / 100


def _fill_missing_technical_fields(item: dict, hist: list[dict], close: float) -> dict:
    closes = [close] + [h["close"] for h in hist if h.get("close")]
    volumes = [item.get("volume") or 0] + [h.get("volume") or 0 for h in hist]
    if not item.get("ma5") and len(closes) >= 5:
        item["ma5"] = sum(closes[:5]) / 5
    if not item.get("ma20") and len(closes) >= 20:
        item["ma20"] = sum(closes[:20]) / 20
    if not item.get("ma60") and len(closes) >= 60:
        item["ma60"] = sum(closes[:60]) / 60
    if not item.get("ma60") and len(closes) >= 20:
        item["ma60_proxy"] = min(closes[:20])
    if not item.get("vol_ratio_5d") and len(volumes) >= 6:
        avg_5 = _average(volumes[1:6])
        if avg_5:
            item["vol_ratio_5d"] = volumes[0] / avg_5
    return item


def _build_quality_features(
    item: dict,
    hist: list[dict],
    close: float,
    distance_ma20: float,
    recent_5d_gain: float,
) -> dict:
    closes = [close] + [h["close"] for h in hist if h.get("close")]
    changes = [item.get("change_pct") or 0] + [h.get("change_pct") or 0 for h in hist]
    volumes = [item.get("volume") or 0] + [h.get("volume") or 0 for h in hist]

    roc_20 = _period_return(hist, 20, close)
    vol_10 = _volatility(closes[:10])
    vol_20 = _volatility(closes[:20])

    up_volumes = [volumes[i] for i, chg in enumerate(changes[:6]) if chg > 0 and volumes[i] > 0]
    down_volumes = [volumes[i] for i, chg in enumerate(changes[:6]) if chg <= 0 and volumes[i] > 0]
    avg_up_volume = _average(up_volumes)
    avg_down_volume = _average(down_volumes)

    volume_price_confirmed = bool(avg_up_volume and avg_down_volume and avg_up_volume > avg_down_volume * 1.15)
    controlled_pullback = bool(avg_down_volume and avg_up_volume and avg_down_volume < avg_up_volume * 0.85)
    volatility_contracting = bool(vol_10 is not None and vol_20 is not None and vol_10 < vol_20 * 0.85)
    momentum_moderate = bool(0 < recent_5d_gain <= 10 and roc_20 is not None and 0 < roc_20 <= 25)

    turnover_rate = item.get("turnover_rate") or 0
    turnover_healthy = 1.0 <= turnover_rate <= 10.0
    price_position_healthy = distance_ma20 <= 0.10

    return {
        "volume_price_confirmed": volume_price_confirmed,
        "controlled_pullback": controlled_pullback,
        "volatility_contracting": volatility_contracting,
        "momentum_moderate": momentum_moderate,
        "turnover_healthy": turnover_healthy,
        "price_position_healthy": price_position_healthy,
        "roc_5d": round(recent_5d_gain, 2),
        "roc_20d": round(roc_20, 2) if roc_20 is not None else None,
        "volatility_10d": round(vol_10, 4) if vol_10 is not None else None,
        "volatility_20d": round(vol_20, 4) if vol_20 is not None else None,
        "avg_up_volume": round(avg_up_volume, 2) if avg_up_volume is not None else None,
        "avg_down_volume": round(avg_down_volume, 2) if avg_down_volume is not None else None,
    }


def _build_reasons(item: dict, trend: dict, quality: dict, distance_ma20: float, bucket: dict) -> list[str]:
    reasons = [bucket["label"]]
    if item.get("technical_fallback"):
        reasons.append("快照历史不足")
    elif bucket["id"] == POOL_TREND:
        reasons.append("MA多头排列")
    elif bucket["id"] == POOL_PULLBACK:
        reasons.append("趋势回踩均线")
    elif bucket["id"] == POOL_REVERSAL:
        reasons.append("跌后反弹观察")

    if trend["r2"] >= 0.55:
        reasons.append("趋势稳定")
    if distance_ma20 <= 0.03:
        reasons.append("贴近MA20")
    elif distance_ma20 <= 0.08:
        reasons.append("价格位置健康")

    if quality.get("volume_price_confirmed"):
        reasons.append("放量上涨")
    if quality.get("controlled_pullback"):
        reasons.append("缩量回调")
    if quality.get("momentum_moderate"):
        reasons.append("动量适中")
    if quality.get("volatility_contracting"):
        reasons.append("波动收窄")
    if quality.get("turnover_healthy"):
        reasons.append("换手适中")

    vol_ratio = item.get("vol_ratio_5d") or 1.0
    if 1.1 <= vol_ratio <= 2.5:
        reasons.append("温和放量")

    return reasons


def _load_recent_history(db, trade_date: str, lookback_days: int) -> dict[str, list[dict]]:
    start = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=lookback_days * 2)).strftime("%Y-%m-%d")
    stmt = text("""
        SELECT symbol, trade_date, close, prev_close, change_pct, volume,
               turnover_rate, ma5, ma20, ma60
        FROM daily_snapshots
        WHERE trade_date > :start_date AND trade_date < :td
        ORDER BY symbol ASC, trade_date DESC
    """)
    rows = db.execute(stmt, {"start_date": start, "td": trade_date}).fetchall()

    history: dict[str, list[dict]] = {}
    for row in rows:
        symbol = row[0]
        if symbol not in history:
            history[symbol] = []
        if len(history[symbol]) < lookback_days:
            history[symbol].append(dict(zip(HISTORY_COLUMNS, row[1:])))
    return history


def _linear_regression(values: list[float]) -> dict | None:
    if len(values) < 20:
        return None

    chronological = list(reversed(values[:20]))
    n = len(chronological)
    mean_x = (n - 1) / 2
    mean_y = sum(chronological) / n
    denominator = sum((i - mean_x) ** 2 for i in range(n))
    if denominator == 0 or mean_y == 0:
        return None

    slope = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(chronological)) / denominator
    fitted = [mean_y + slope * (i - mean_x) for i in range(n)]
    ss_tot = sum((y - mean_y) ** 2 for y in chronological)
    if ss_tot == 0:
        return None
    ss_res = sum((y - fitted[i]) ** 2 for i, y in enumerate(chronological))
    r2 = max(0.0, 1 - ss_res / ss_tot)

    return {
        "slope": slope,
        "slope_pct": slope / mean_y * 100,
        "r2": r2,
    }


def _period_return(hist: list[dict], days: int, current_close: float) -> float | None:
    if len(hist) < days:
        return None
    base_close = hist[days - 1].get("close")
    if not base_close:
        return None
    return (current_close / base_close - 1) * 100


def _volatility(values: list[float]) -> float | None:
    clean = [v for v in values if v]
    if len(clean) < 5:
        return None
    returns = [(clean[i] / clean[i + 1] - 1) for i in range(len(clean) - 1) if clean[i + 1]]
    if len(returns) < 4:
        return None
    avg = sum(returns) / len(returns)
    variance = sum((r - avg) ** 2 for r in returns) / len(returns)
    return variance ** 0.5


def _average(values: list[float]) -> float | None:
    clean = [v for v in values if v]
    if not clean:
        return None
    return sum(clean) / len(clean)
