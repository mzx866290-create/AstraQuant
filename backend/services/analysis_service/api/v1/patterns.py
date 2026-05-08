"""
K线形态识别 API — 基于真实OHLC关系的9种经典形态检测
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from datetime import datetime
import sys
import os

router = APIRouter(tags=["K线形态"])

PATTERNS = {
    "doji": "十字星 — 开盘收盘价接近，市场犹豫",
    "hammer": "锤子线 — 下影线长，反转看涨信号",
    "shooting_star": "射击之星 — 上影线长，反转看跌信号",
    "engulfing_bull": "阳包阴 — 阳线实体包裹前日阴线，看涨",
    "engulfing_bear": "阴包阳 — 阴线实体包裹前日阳线，看跌",
    "three_white_soldiers": "三白兵 — 连续三根阳线，强势看涨",
    "three_black_crows": "三只乌鸦 — 连续三根阴线，强势看跌",
    "morning_star": "晨星 — 长阴+小实体+长阳，底部反转看涨",
    "evening_star": "暮星 — 长阳+小实体+长阴，顶部反转看跌",
}


def _body(bar: dict) -> float:
    return abs(bar["close"] - bar["open"])


def _upper_shadow(bar: dict) -> float:
    return bar["high"] - max(bar["close"], bar["open"])


def _lower_shadow(bar: dict) -> float:
    return min(bar["close"], bar["open"]) - bar["low"]


def _is_bullish(bar: dict) -> bool:
    return bar["close"] > bar["open"]


def _is_bearish(bar: dict) -> bool:
    return bar["close"] < bar["open"]


def _avg_body(bars: list[dict], n: int = 20) -> float:
    bodies = [_body(b) for b in bars[-n:]]
    return sum(bodies) / len(bodies) if bodies else 1


def detect_doji(bars: list[dict], i: int) -> Optional[dict]:
    """十字星: 实体极小，上下影线相近"""
    bar = bars[i]
    avg = _avg_body(bars[:i+1], min(20, i+1))
    if avg == 0:
        return None
    body_ratio = _body(bar) / avg
    if body_ratio > 0.3:
        return None
    us = _upper_shadow(bar)
    ls = _lower_shadow(bar)
    if us + ls < avg * 0.5:
        return None
    return {"name": "doji", "signal": "反转", "confidence": "中",
            "description": f"实体/均比={body_ratio:.2f}, 上影={us:.2f}, 下影={ls:.2f}"}


def detect_hammer(bars: list[dict], i: int) -> Optional[dict]:
    """锤子线: 下影线>=实体2倍, 上影线很短，出现在下跌后"""
    bar = bars[i]
    body_val = _body(bar)
    if body_val == 0:
        return None
    ls = _lower_shadow(bar)
    us = _upper_shadow(bar)
    if ls < body_val * 2:
        return None
    if us > body_val * 0.3:
        return None
    if i > 0 and bars[i-1]["close"] <= bar["close"]:
        return None  # 不在下跌趋势后
    return {"name": "hammer", "signal": "看涨反转", "confidence": "中",
            "description": f"下影/实体={ls/body_val:.2f}x, 上影极小"}


def detect_shooting_star(bars: list[dict], i: int) -> Optional[dict]:
    """射击之星: 上影线>=实体2倍，下影线很短，出现在上涨后"""
    bar = bars[i]
    body_val = _body(bar)
    if body_val == 0:
        return None
    us = _upper_shadow(bar)
    ls = _lower_shadow(bar)
    if us < body_val * 2:
        return None
    if ls > body_val * 0.3:
        return None
    if i > 0 and bars[i-1]["close"] >= bar["close"]:
        return None
    return {"name": "shooting_star", "signal": "看跌反转", "confidence": "中",
            "description": f"上影/实体={us/body_val:.2f}x, 下影极小"}


def detect_engulfing_bull(bars: list[dict], i: int) -> Optional[dict]:
    """阳包阴: 前日阴线实体被今日阳线完全包裹"""
    if i < 1:
        return None
    cur, prev = bars[i], bars[i-1]
    if not _is_bullish(cur) or not _is_bearish(prev):
        return None
    if cur["open"] >= prev["close"] or cur["close"] <= prev["open"]:
        return None
    return {"name": "engulfing_bull", "signal": "看涨反转", "confidence": "高",
            "description": f"阳线({cur['open']:.2f}-{cur['close']:.2f})包裹阴线({prev['open']:.2f}-{prev['close']:.2f})"}


def detect_engulfing_bear(bars: list[dict], i: int) -> Optional[dict]:
    """阴包阳: 前日阳线实体被今日阴线完全包裹"""
    if i < 1:
        return None
    cur, prev = bars[i], bars[i-1]
    if not _is_bearish(cur) or not _is_bullish(prev):
        return None
    if cur["open"] <= prev["close"] or cur["close"] >= prev["open"]:
        return None
    return {"name": "engulfing_bear", "signal": "看跌反转", "confidence": "高",
            "description": f"阴线包裹前日阳线实体"}


def detect_three_white_soldiers(bars: list[dict], i: int) -> Optional[dict]:
    """三白兵: 连续三根阳线，每根收盘>前日收盘，实体适中"""
    if i < 2:
        return None
    a, b, c = bars[i-2], bars[i-1], bars[i]
    if not all(_is_bullish(x) for x in [a, b, c]):
        return None
    if not (c["close"] > b["close"] > a["close"]):
        return None
    avg = _avg_body(bars[:i+1], min(20, i+1))
    if any(_body(x) < avg * 0.5 for x in [a, b, c]):
        return None
    return {"name": "three_white_soldiers", "signal": "强势看涨", "confidence": "高",
            "description": "连续三阳线，收盘价递增"}


def detect_three_black_crows(bars: list[dict], i: int) -> Optional[dict]:
    """三只乌鸦: 连续三根阴线，每根收盘<前日收盘"""
    if i < 2:
        return None
    a, b, c = bars[i-2], bars[i-1], bars[i]
    if not all(_is_bearish(x) for x in [a, b, c]):
        return None
    if not (c["close"] < b["close"] < a["close"]):
        return None
    avg = _avg_body(bars[:i+1], min(20, i+1))
    if any(_body(x) < avg * 0.5 for x in [a, b, c]):
        return None
    return {"name": "three_black_crows", "signal": "强势看跌", "confidence": "高",
            "description": "连续三阴线，收盘价递减"}


def detect_morning_star(bars: list[dict], i: int) -> Optional[dict]:
    """晨星: 长阴 + 小实体(可阴可阳) + 长阳"""
    if i < 2:
        return None
    a, b, c = bars[i-2], bars[i-1], bars[i]
    avg = _avg_body(bars[:i+1], min(20, i+1))
    if not _is_bearish(a) or _body(a) < avg:
        return None
    if _body(b) > avg * 0.5:
        return None
    if not _is_bullish(c) or _body(c) < avg:
        return None
    if c["close"] <= (a["open"] + a["close"]) / 2:
        return None
    return {"name": "morning_star", "signal": "底部反转看涨", "confidence": "高",
            "description": "长阴→小实体→长阳，底部反转信号"}


def detect_evening_star(bars: list[dict], i: int) -> Optional[dict]:
    """暮星: 长阳 + 小实体 + 长阴"""
    if i < 2:
        return None
    a, b, c = bars[i-2], bars[i-1], bars[i]
    avg = _avg_body(bars[:i+1], min(20, i+1))
    if not _is_bullish(a) or _body(a) < avg:
        return None
    if _body(b) > avg * 0.5:
        return None
    if not _is_bearish(c) or _body(c) < avg:
        return None
    if c["close"] >= (a["open"] + a["close"]) / 2:
        return None
    return {"name": "evening_star", "signal": "顶部反转看跌", "confidence": "高",
            "description": "长阳→小实体→长阴，顶部反转信号"}


DETECTORS = [
    detect_doji, detect_hammer, detect_shooting_star,
    detect_engulfing_bull, detect_engulfing_bear,
    detect_three_white_soldiers, detect_three_black_crows,
    detect_morning_star, detect_evening_star,
]


@router.get("/{symbol}")
async def detect_patterns(
    symbol: str,
    limit: int = Query(30, ge=10, le=200, description="检测周期数"),
):
    """
    检测A股K线形态 — 基于真实OHLC数据

    支持识别: 十字星/锤子线/射击之星/阳包阴/阴包阳/
             三白兵/三只乌鸦/晨星/暮星
    """
    from .scoring import _fetch_recent_kline

    try:
        kline_data = await _fetch_recent_kline(symbol, limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"K线数据源不可用: {e}")
    if len(kline_data) < 5:
        return {"symbol": symbol, "patterns": [], "count": 0,
                "error": "K线数据不足"}

    found = []
    for i in range(len(kline_data)):
        for detector in DETECTORS:
            result = detector(kline_data, i)
            if result:
                bar = kline_data[i]
                result["date"] = bar.get("date", "")
                result["price"] = bar.get("close", 0)
                found.append(result)

    # 按日期倒序，每种形态只保留最新一个
    found.sort(key=lambda x: x.get("date", ""), reverse=True)
    seen_names = set()
    unique = []
    for p in found:
        if p["name"] not in seen_names:
            seen_names.add(p["name"])
            unique.append(p)

    return {
        "symbol": symbol,
        "patterns": unique[:10],
        "count": len(found),
        "data_points": len(kline_data),
        "updated_at": datetime.now().isoformat(),
    }


@router.get("/list")
async def list_patterns():
    """列出所有支持的K线形态"""
    return {
        "total": len(PATTERNS),
        "patterns": [{"name": k, "description": v} for k, v in PATTERNS.items()],
    }
