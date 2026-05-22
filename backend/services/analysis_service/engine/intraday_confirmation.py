"""Intraday confirmation layer for the daily observation pool."""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from typing import Any

from backend.services.market_service.app.api.v1.quotes import get_quote

CONFIRMATION_WINDOWS = ((9, 35), (9, 45), (10, 0))


def next_confirmation_target(now: datetime | None = None) -> datetime:
    current = now or datetime.now()
    for hour, minute in CONFIRMATION_WINDOWS:
        target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if current < target:
            return target
    next_day = current + timedelta(days=1)
    return next_day.replace(
        hour=CONFIRMATION_WINDOWS[0][0],
        minute=CONFIRMATION_WINDOWS[0][1],
        second=0,
        microsecond=0,
    )


def confirmation_window_label(now: datetime | None = None) -> str:
    current = now or datetime.now()
    if current.time() < time(9, 35):
        return "preopen"
    if current.time() < time(9, 45):
        return "09:35"
    if current.time() < time(10, 0):
        return "09:45"
    return "10:00"


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default


def _news_direction(row: dict) -> str:
    optimizer_news = ((row.get("pool_optimizer") or {}).get("news") or {}).get("direction")
    if optimizer_news:
        return str(optimizer_news).lower()
    for item in row.get("evidence_chain") or []:
        if isinstance(item, dict) and item.get("factor") == "news_impact_agent":
            value = item.get("value") if isinstance(item.get("value"), dict) else {}
            return str(value.get("direction") or item.get("direction") or "neutral").lower()
    return "neutral"


def _quote_quality(quote: dict) -> dict:
    quality = quote.get("data_quality") if isinstance(quote.get("data_quality"), dict) else {}
    return {
        "source": quote.get("source") or quality.get("source") or "unknown",
        "freshness": quality.get("freshness") or "unknown",
        "status": quality.get("status") or "unknown",
        "is_fallback": bool(quality.get("is_fallback")),
        "warnings": quality.get("warnings") or [],
    }


def confirm_recommendation(row: dict, quote: dict, *, now: datetime | None = None) -> dict:
    current = now or datetime.now()
    price = _to_float(quote.get("price"))
    open_price = _to_float(quote.get("open"))
    low = _to_float(quote.get("low"))
    high = _to_float(quote.get("high"))
    change_pct = _to_float(quote.get("change_pct"))
    prev_close = price - _to_float(quote.get("change")) if price else 0.0
    if prev_close <= 0 and price and change_pct != -100:
        prev_close = price / (1 + change_pct / 100)
    open_gap_pct = ((open_price - prev_close) / prev_close * 100) if prev_close and open_price else None
    intraday_from_open_pct = ((price - open_price) / open_price * 100) if price and open_price else None

    action = str(row.get("observation_action") or "")
    bucket = str(row.get("observation_bucket") or "")
    news_direction = _news_direction(row)
    priority = int(_to_float(row.get("priority_score")))
    quality = _quote_quality(quote)

    status = "watch_only"
    label = "仅观察"
    reasons: list[str] = []
    next_action = "等待盘中走势确认，不追高。"
    risk_level = "medium"

    if quality["is_fallback"]:
        status = "quote_degraded"
        label = "行情降级"
        reasons.append("实时行情降级，当前确认结果仅供参考")
        next_action = "等待实时行情源恢复后再判断。"
        risk_level = "high"
    elif news_direction == "negative" and priority <= 20:
        status = "watch_only"
        label = "消息验证"
        reasons.append("隔夜资讯偏负，优先验证承接而不是主动出手")
        next_action = "只观察开盘承接，未放量转强前不进入可关注。"
        risk_level = "high"
    elif change_pct <= -2.0 or (
        open_price
        and low
        and price <= low * 1.005
        and intraday_from_open_pct is not None
        and intraday_from_open_pct < -1.0
    ):
        status = "invalidated"
        label = "已失效"
        reasons.append("盘中跌幅或开盘后回落触发失效条件")
        next_action = "从今日可操作候选中剔除，只保留复盘观察。"
        risk_level = "high"
    elif open_gap_pct is not None and open_gap_pct >= 3.0 and intraday_from_open_pct is not None and intraday_from_open_pct < 0.5:
        status = "wait_pullback"
        label = "等回踩"
        reasons.append("高开后承接不足，追高性价比下降")
        next_action = "等待回踩企稳或重新放量突破，不追开盘高点。"
        risk_level = "medium"
    elif change_pct >= 5.0:
        status = "wait_pullback"
        label = "涨幅兑现"
        reasons.append("盘中涨幅已较大，更多是持有/观察，不适合新追")
        next_action = "等分时回踩和量能确认，避免情绪高点追入。"
        risk_level = "medium"
    elif price and open_price and low and price >= open_price and price > low * 1.01 and priority >= 30:
        status = "actionable"
        label = "可关注"
        reasons.append("开盘后未破承接区，且当前价格重新站回开盘附近")
        next_action = "仅在回踩不破失效条件时小仓位观察，跌破立即放弃。"
        risk_level = "low"
    elif action == "回踩承接" or bucket == "pullback_support":
        status = "wait_pullback"
        label = "等回踩"
        reasons.append("符合观察池逻辑，但盘中确认还不充分")
        next_action = "等回踩企稳、量能温和放大后再纳入可关注。"
        risk_level = "medium"

    if open_gap_pct is not None and open_gap_pct >= 3.0:
        reasons.append("开盘高开超过 3%，需严格避免追高")
    if news_direction == "positive":
        reasons.append("隔夜资讯偏正面")
    elif news_direction == "negative":
        reasons.append("隔夜资讯偏负面")

    return {
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "status": status,
        "label": label,
        "risk_level": risk_level,
        "next_action": next_action,
        "reasons": list(dict.fromkeys(reasons))[:4],
        "checked_at": current.isoformat(),
        "window": confirmation_window_label(current),
        "quote": {
            "price": price,
            "change_pct": change_pct,
            "open": open_price,
            "high": high,
            "low": low,
            "open_gap_pct": round(open_gap_pct, 2) if open_gap_pct is not None else None,
            "intraday_from_open_pct": round(intraday_from_open_pct, 2) if intraday_from_open_pct is not None else None,
            "quality": quality,
        },
    }


async def build_intraday_confirmation(rows: list[dict], *, now: datetime | None = None, concurrency: int = 8) -> dict:
    current = now or datetime.now()
    semaphore = asyncio.Semaphore(max(1, min(int(concurrency or 8), 20)))

    async def _confirm(row: dict) -> dict:
        async with semaphore:
            try:
                quote = await get_quote(str(row.get("symbol") or ""))
                return confirm_recommendation(row, quote, now=current)
            except Exception as exc:
                return {
                    "symbol": row.get("symbol"),
                    "name": row.get("name"),
                    "status": "quote_error",
                    "label": "行情失败",
                    "risk_level": "high",
                    "next_action": "行情不可用，暂不做盘中确认。",
                    "reasons": [str(exc)[:120]],
                    "checked_at": current.isoformat(),
                    "window": confirmation_window_label(current),
                    "quote": {"quality": {"status": "error", "warnings": ["quote_fetch_failed"]}},
                }

    confirmations = await asyncio.gather(*[_confirm(row) for row in rows])
    counts: dict[str, int] = {}
    for item in confirmations:
        counts[item["status"]] = counts.get(item["status"], 0) + 1

    actionable = counts.get("actionable", 0)
    invalidated = counts.get("invalidated", 0)
    summary = {
        "pool_state": "active" if actionable else "observe_only",
        "message": (
            f"{actionable} 只进入盘中可关注，{invalidated} 只触发失效/剔除。"
            if actionable else
            "当前没有足够强的盘中确认，观察池以等待和风控为主。"
        ),
        "counts": counts,
    }
    return {
        "status": "ok",
        "checked_at": current.isoformat(),
        "window": confirmation_window_label(current),
        "next_window_at": next_confirmation_target(current).isoformat(),
        "summary": summary,
        "items": confirmations,
    }

