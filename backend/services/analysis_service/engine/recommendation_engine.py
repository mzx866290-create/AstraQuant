"""Daily recommendation candidate pool and scoring helpers."""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, datetime
from typing import Optional

from backend.services.analysis_service.engine.strategy_rule_scoring import configured_rule_result

logger = logging.getLogger(__name__)

_FALLBACK_CANDIDATE_WARNING = (
    "recommendation candidate pool is empty; using static development fallback candidates"
)
_SMALL_CANDIDATE_POOL_WARNING = (
    "database candidate pool is small; supplemented with static development fallback candidates"
)
_PRODUCTION_SMALL_CANDIDATE_POOL_WARNING = (
    "database candidate pool is small; production recommendations use database candidates only"
)


def _candidate_code(row: dict) -> str:
    symbol = str(row.get("symbol") or "").strip().upper()
    base = symbol.split(".", 1)[0]
    digits = "".join(ch for ch in base if ch.isdigit())
    return digits[:6]


def _candidate_rotation_key(row: dict, rotation_date: date) -> tuple[int, str]:
    code = _candidate_code(row)
    try:
        code_number = int(code)
    except ValueError:
        code_number = sum(ord(ch) for ch in code)
    market_salt = 0x9E3779B9 if row.get("market") == "SH" else 0x85EBCA6B
    day_seed = rotation_date.toordinal()
    return ((code_number * 1103515245 + day_seed * 2654435761 + market_salt) & 0xFFFFFFFF, code)


def _select_rotated_candidates(universe: list[dict], sample_size: int, rotation_date: date) -> list[dict]:
    if sample_size <= 0 or not universe:
        return []

    ordered = sorted((dict(row) for row in universe), key=lambda row: _candidate_rotation_key(row, rotation_date))
    selected: list[dict] = []
    overflow: list[dict] = []
    sector_counts: dict[str, int] = {}
    sector_cap = max(2, math.ceil(sample_size / 10))

    for row in ordered:
        sector = row.get("sector") or "__unknown__"
        if sector_counts.get(sector, 0) < sector_cap:
            selected.append(row)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        else:
            overflow.append(row)
        if len(selected) >= sample_size:
            break

    if len(selected) < sample_size:
        seen_codes = {_candidate_code(row) for row in selected}
        for row in overflow:
            code = _candidate_code(row)
            if not code or code in seen_codes:
                continue
            selected.append(row)
            seen_codes.add(code)
            if len(selected) >= sample_size:
                break

    return selected[:sample_size]


def _supplement_development_candidates(
    db_candidates: list[dict],
    fallback_candidates: list[dict],
    candidate_limit: int,
) -> tuple[list[dict], str, list[str], set[str]]:
    if not db_candidates:
        candidates = [dict(row) for row in fallback_candidates[:candidate_limit]]
        fallback_codes = {_candidate_code(row) for row in candidates if _candidate_code(row)}
        return candidates, "fallback", [_FALLBACK_CANDIDATE_WARNING], fallback_codes

    if len(db_candidates) >= candidate_limit:
        return db_candidates, "db", [], set()

    merged = [dict(row) for row in db_candidates]
    seen_codes = {_candidate_code(row) for row in merged if _candidate_code(row)}
    fallback_codes: set[str] = set()

    for row in fallback_candidates:
        code = _candidate_code(row)
        if not code or code in seen_codes:
            continue
        merged.append(dict(row))
        seen_codes.add(code)
        fallback_codes.add(code)
        if len(merged) >= candidate_limit:
            break

    if not fallback_codes:
        return db_candidates, "db", [], set()

    return merged, "mixed", [_SMALL_CANDIDATE_POOL_WARNING], fallback_codes


def _mark_fallback_recommendations(scored: list[dict], fallback_codes: set[str]) -> list[dict]:
    if not fallback_codes:
        return scored
    return [
        _mark_fallback_recommendation(item) if _candidate_code(item) in fallback_codes else item
        for item in scored
    ]


def _empty_recommendations_result(
    *,
    market: str,
    strategy: str,
    candidate_limit: int,
    concurrency: int,
    warnings: list[str],
) -> dict:
    return {
        "recommendations": [],
        "market": market,
        "status": "unavailable",
        "candidate_source": "db",
        "warnings": warnings,
        "count": 0,
        "candidate_count": 0,
        "candidate_universe_count": 0,
        "scored_count": 0,
        "concurrency": concurrency,
        "max_candidates": candidate_limit,
        "selection": {
            "mode": "none",
            "rotation_date": datetime.now().date().isoformat(),
            "universe_count": 0,
            "evaluated_count": 0,
        },
        "cache_hit": False,
        "updated_at": datetime.now().isoformat(),
        "method": {
            "name": "daily_observation_pool_v1",
            "description": "candidate pool unavailable; recommendations were not generated",
            "strategy": strategy,
        },
        "data_grade": {
            "grade": "D",
            "source": "db",
            "warnings": warnings,
        },
        "disclaimer": "Daily observation pool is unavailable because no database candidates were found.",
    }


def _mark_fallback_recommendation(item: dict) -> dict:
    data_grade = dict(item.get("data_grade") or {})
    grade_warnings = list(data_grade.get("warnings") or [])
    if _FALLBACK_CANDIDATE_WARNING not in grade_warnings:
        grade_warnings.append(_FALLBACK_CANDIDATE_WARNING)

    marked = dict(item)
    marked["candidate_source"] = "fallback"
    marked["source"] = "fallback"
    marked["warnings"] = list(dict.fromkeys([*(item.get("warnings") or []), _FALLBACK_CANDIDATE_WARNING]))
    marked["data_grade"] = {
        **data_grade,
        "source": data_grade.get("source") or "fallback",
        "candidate_source": "fallback",
        "warnings": grade_warnings,
    }
    return marked


async def _evaluate_candidates_parallel(
    candidates: list[dict],
    strategy: str,
    concurrency: int = 16,
    timeout_seconds: float = 25.0,
) -> list[dict]:
    semaphore = asyncio.Semaphore(concurrency)

    async def evaluate(row: dict) -> Optional[dict]:
        async with semaphore:
            try:
                return await asyncio.wait_for(_evaluate_daily_candidate(row, strategy), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                logger.debug("daily candidate evaluation timed out for %s", row.get("symbol"))
                return None

    results = await asyncio.gather(*(evaluate(row) for row in candidates), return_exceptions=True)
    scored: list[dict] = []
    for item in results:
        if isinstance(item, Exception):
            logger.debug("daily candidate evaluation task failed: %s", item)
            continue
        if item:
            scored.append(item)
    return scored


def _load_recommendation_candidates(market: str, sample_size: int, rotation_date: date | None = None) -> list[dict]:
    from backend.shared.database import SessionLocal
    from backend.shared.models import Stock

    seen = set()
    rotation_date = rotation_date or datetime.now().date()

    def normalize(row: dict) -> dict | None:
        code = (row.get("symbol") or "")[:6]
        if not code or code in seen:
            return None
        row_market = row.get("market") or ("SH" if code.startswith(("6", "9")) else "SZ")
        if row_market not in ("SH", "SZ"):
            return None
        if market != "ALL" and row_market != market:
            return None
        name = row.get("name") or code
        if "退" in name or name.startswith(("*ST", "ST")):
            return
        seen.add(code)
        return {
            "symbol": f"{code}.{row_market}",
            "name": name,
            "market": row_market,
            "sector": row.get("sector") or "",
        }

    db = SessionLocal()
    try:
        markets = [market] if market in ("SH", "SZ") else ["SH", "SZ"]
        per_market = max(1, math.ceil(sample_size / len(markets)))
        universes_by_market: dict[str, list[dict]] = {m: [] for m in markets}
        for m in markets:
            rows = (
                db.query(Stock)
                .filter(Stock.is_active == True, Stock.market == m)
                .order_by(Stock.id.asc())
                .all()
            )
            for row in rows:
                candidate = normalize({
                    "symbol": row.symbol,
                    "name": row.name,
                    "market": row.market,
                    "sector": row.sector or "",
                })
                if candidate:
                    universes_by_market[m].append(candidate)

        universe_count = sum(len(items) for items in universes_by_market.values())
        result: list[dict] = []
        for m in markets:
            result.extend(_select_rotated_candidates(universes_by_market[m], per_market, rotation_date))

        if len(result) < sample_size:
            selected_codes = {_candidate_code(row) for row in result}
            remainder = [
                row
                for rows in universes_by_market.values()
                for row in rows
                if _candidate_code(row) not in selected_codes
            ]
            for row in _select_rotated_candidates(remainder, sample_size - len(result), rotation_date):
                selected_codes.add(_candidate_code(row))
                result.append(row)
                if len(result) >= sample_size:
                    break

        for row in result[:sample_size]:
            row["_candidate_universe_count"] = universe_count
            row["_candidate_rotation_date"] = rotation_date.isoformat()
            row["_candidate_selection"] = "daily_rotating_db_sample"
        return result[:sample_size]
    finally:
        db.close()


def _fallback_recommendation_candidates(market: str) -> list[dict]:
    rows = [
        {"symbol": "600887.SH", "name": "伊利股份", "market": "SH", "sector": "食品饮料"},
        {"symbol": "600690.SH", "name": "海尔智家", "market": "SH", "sector": "家用电器"},
        {"symbol": "600004.SH", "name": "白云机场", "market": "SH", "sector": "交通运输"},
        {"symbol": "601006.SH", "name": "大秦铁路", "market": "SH", "sector": "铁路"},
        {"symbol": "600383.SH", "name": "金地集团", "market": "SH", "sector": "房地产"},
        {"symbol": "000651.SZ", "name": "格力电器", "market": "SZ", "sector": "家用电器"},
        {"symbol": "000333.SZ", "name": "美的集团", "market": "SZ", "sector": "家用电器"},
        {"symbol": "002508.SZ", "name": "老板电器", "market": "SZ", "sector": "家用电器"},
        {"symbol": "002032.SZ", "name": "苏泊尔", "market": "SZ", "sector": "家用电器"},
        {"symbol": "002271.SZ", "name": "东方雨虹", "market": "SZ", "sector": "建筑材料"},
        {"symbol": "002415.SZ", "name": "海康威视", "market": "SZ", "sector": "计算机"},
        {"symbol": "000002.SZ", "name": "万科A", "market": "SZ", "sector": "房地产"},
        {"symbol": "600019.SH", "name": "宝钢股份", "market": "SH", "sector": "钢铁"},
        {"symbol": "600031.SH", "name": "三一重工", "market": "SH", "sector": "机械设备"},
        {"symbol": "600048.SH", "name": "保利发展", "market": "SH", "sector": "房地产"},
        {"symbol": "600089.SH", "name": "特变电工", "market": "SH", "sector": "电力设备"},
        {"symbol": "600406.SH", "name": "国电南瑞", "market": "SH", "sector": "电力设备"},
        {"symbol": "600585.SH", "name": "海螺水泥", "market": "SH", "sector": "建筑材料"},
        {"symbol": "600703.SH", "name": "三安光电", "market": "SH", "sector": "电子"},
        {"symbol": "601186.SH", "name": "中国铁建", "market": "SH", "sector": "建筑装饰"},
        {"symbol": "601390.SH", "name": "中国中铁", "market": "SH", "sector": "建筑装饰"},
        {"symbol": "601899.SH", "name": "紫金矿业", "market": "SH", "sector": "有色金属"},
        {"symbol": "000001.SZ", "name": "平安银行", "market": "SZ", "sector": "银行"},
        {"symbol": "000100.SZ", "name": "TCL科技", "market": "SZ", "sector": "电子"},
        {"symbol": "000157.SZ", "name": "中联重科", "market": "SZ", "sector": "机械设备"},
        {"symbol": "000338.SZ", "name": "潍柴动力", "market": "SZ", "sector": "汽车"},
        {"symbol": "000425.SZ", "name": "徐工机械", "market": "SZ", "sector": "机械设备"},
        {"symbol": "000625.SZ", "name": "长安汽车", "market": "SZ", "sector": "汽车"},
        {"symbol": "000725.SZ", "name": "京东方A", "market": "SZ", "sector": "电子"},
        {"symbol": "002027.SZ", "name": "分众传媒", "market": "SZ", "sector": "传媒"},
        {"symbol": "002120.SZ", "name": "韵达股份", "market": "SZ", "sector": "交通运输"},
        {"symbol": "002241.SZ", "name": "歌尔股份", "market": "SZ", "sector": "电子"},
        {"symbol": "002475.SZ", "name": "立讯精密", "market": "SZ", "sector": "电子"},
        {"symbol": "002555.SZ", "name": "三七互娱", "market": "SZ", "sector": "传媒"},
    ]
    return [row for row in rows if market == "ALL" or row["market"] == market]


async def _evaluate_daily_candidate(row: dict, strategy: str = "retail_small") -> Optional[dict]:
    try:
        from backend.services.analysis_service.engine.context_builder import context_builder
        from backend.services.analysis_service.engine.ai_analysis_data import get_stock_data
        from backend.services.analysis_service.engine.ai_analysis_fallbacks import build_risk_lights

        stock_data = await get_stock_data(row["symbol"], include_news=True, include_profile=False)
        stock_data = context_builder.enrich(stock_data, models_count=1, quota_ready=True, quota_message="")
        readiness = stock_data.get("readiness") or {}
        data_grade = readiness.get("data_grade") or {}
        if data_grade.get("grade") == "D":
            return None

        risk_lights = build_risk_lights(stock_data)
        score, reasons, risk_flags = _score_daily_candidate(stock_data, risk_lights, strategy)
        if score < 55:
            return None
        score_breakdown = _build_score_breakdown(stock_data, risk_lights, strategy)

        quote = stock_data.get("quote") or {}
        financial = stock_data.get("financial") or {}
        industry = stock_data.get("industry_event_context") or {}
        price = float(stock_data.get("price") or 0)
        lot_cost = round(price * 100, 2) if price > 0 else None
        total_mv = financial.get("total_mv") or quote.get("total_mv")
        return {
            "symbol": row["symbol"],
            "name": stock_data.get("name") or row.get("name") or row["symbol"],
            "market": row.get("market"),
            "sector": stock_data.get("sector") or row.get("sector") or "",
            "price": stock_data.get("price"),
            "lot_cost": lot_cost,
            "change_pct": stock_data.get("change_pct"),
            "pe_ttm": financial.get("pe_ttm") or quote.get("pe_ttm"),
            "pb": financial.get("pb") or quote.get("pb"),
            "total_mv": total_mv,
            "score": score,
            "rating": _daily_rating(score),
            "reasons": reasons[:4],
            "risk_flags": risk_flags[:4],
            "score_breakdown": score_breakdown,
            "data_grade": data_grade,
            "risk_lights": risk_lights,
            "stock_data": stock_data,
            "industry_themes": [t.get("theme") for t in (industry.get("themes") or [])[:3] if t.get("theme")],
            "updated_at": datetime.now().isoformat(),
        }
    except Exception as exc:
        logger.debug("daily candidate evaluation failed for %s: %s", row.get("symbol"), exc)
        return None



def _configured_daily_factor_keys(strategy: str) -> tuple[str, ...]:
    keys = ["data_quality", "technical", "volume", "valuation", "financial_quality"]
    if strategy == "retail_small":
        keys = ["retail_affordability", "market_cap", *keys]
    return tuple(keys)


def _configured_daily_rule_result(stock_data: dict, strategy: str, factor: str) -> dict | None:
    result = configured_rule_result(stock_data, strategy, factor)
    if not result:
        return None
    result.setdefault("key", factor)
    result.setdefault("label", factor)
    result.setdefault("delta", 0)
    result.setdefault("status", "positive" if result["delta"] > 0 else "negative" if result["delta"] < 0 else "neutral")
    result.setdefault("message", f"{factor}: {result.get('bucket') or 'matched'}")
    return result


def _append_configured_daily_rule(
    stock_data: dict,
    strategy: str,
    factor: str,
    reasons: list[str],
    risk_flags: list[str],
) -> int:
    result = _configured_daily_rule_result(stock_data, strategy, factor)
    if not result:
        return 0
    delta = int(result.get("delta") or 0)
    components = result.get("components") if isinstance(result.get("components"), list) else []
    messages = components or [result]
    for item in messages:
        item_delta = int(item.get("delta") or 0)
        message = str(item.get("message") or item.get("bucket") or factor)
        value = item.get("value")
        if item.get("metric") and isinstance(value, (int, float)):
            message = f"{message}: {float(value):.1f}"
        if item_delta > 0:
            reasons.append(message)
        elif item_delta < 0:
            risk_flags.append(message)
    return delta


def _score_daily_candidate(stock_data: dict, risk_lights: dict, strategy: str = "retail_small") -> tuple[int, list[str], list[str]]:
    sentiment = stock_data.get("news_sentiment") or {}
    industry = stock_data.get("industry_event_context") or {}
    score = 50.0
    reasons: list[str] = []
    risk_flags: list[str] = []

    for factor in _configured_daily_factor_keys(strategy):
        score += _append_configured_daily_rule(stock_data, strategy, factor, reasons, risk_flags)

    weighted = sentiment.get("weighted_dominant_sentiment")
    if weighted in ("姝ｉ潰", "positive"):
        score += 5
        reasons.append("weighted news sentiment is positive")
    elif weighted in ("璐熼潰", "negative"):
        score -= 8
        risk_flags.append(sentiment.get("validation_note") or "weighted news sentiment is negative")

    if industry.get("available"):
        score += 3
        themes = ", ".join(t.get("theme", "") for t in (industry.get("themes") or [])[:2] if t.get("theme"))
        if themes:
            reasons.append(f"industry/theme evidence available: {themes}")

    for key, item in risk_lights.items():
        level = item.get("level")
        if level == "red":
            score -= 18
            risk_flags.append(item.get("message") or f"{key} red light")
        elif level == "yellow":
            score -= 2

    score = int(max(0, min(100, round(score))))
    if not reasons:
        reasons.append("no clear exclusion signal found, but further research is still required")
    if not risk_flags:
        risk_flags.append("no obvious red light found, but market volatility still needs monitoring")
    return score, reasons, risk_flags


def _build_score_breakdown(stock_data: dict, risk_lights: dict, strategy: str = "retail_small") -> list[dict]:
    sentiment = stock_data.get("news_sentiment") or {}
    industry = stock_data.get("industry_event_context") or {}
    items: list[dict] = [
        {"key": "base", "label": "base", "delta": 50, "status": "neutral", "message": "base observation score"}
    ]

    def add(key: str, label: str, delta: int, message: str, status: str | None = None) -> None:
        if status is None:
            status = "positive" if delta > 0 else "negative" if delta < 0 else "neutral"
        items.append({"key": key, "label": label, "delta": delta, "status": status, "message": message})

    for factor in _configured_daily_factor_keys(strategy):
        result = _configured_daily_rule_result(stock_data, strategy, factor)
        if result:
            components = result.get("components") if isinstance(result.get("components"), list) else []
            if components:
                for component in components:
                    message = str(component.get("message") or component.get("bucket") or factor)
                    value = component.get("value")
                    if component.get("metric") and isinstance(value, (int, float)):
                        message = f"{message}: {float(value):.1f}"
                    add(
                        str(component.get("key") or factor),
                        str(component.get("label") or result.get("label") or factor),
                        int(component.get("delta") or 0),
                        message,
                        str(component.get("status") or "neutral"),
                    )
                continue
            message = str(result.get("message") or result.get("bucket") or factor)
            if factor == "technical" and result.get("ret5") is not None and result.get("ret20") is not None:
                message = f"{message}: 5d {float(result['ret5']):+.1f}%, 20d {float(result['ret20']):+.1f}%"
            elif factor == "volume" and result.get("ratio") is not None:
                message = f"{message}: ratio {float(result['ratio']):.2f}"
            add(
                str(result.get("key") or factor),
                str(result.get("label") or factor),
                int(result.get("delta") or 0),
                message,
                str(result.get("status") or "neutral"),
            )

    weighted = sentiment.get("weighted_dominant_sentiment")
    if weighted in ("姝ｉ潰", "positive"):
        add("news_sentiment", "news_sentiment", 5, "weighted news sentiment is positive")
    elif weighted in ("璐熼潰", "negative"):
        add("news_sentiment", "news_sentiment", -8, sentiment.get("validation_note") or "weighted news sentiment is negative")

    if industry.get("available"):
        themes = ", ".join(t.get("theme", "") for t in (industry.get("themes") or [])[:2] if t.get("theme"))
        add("industry_theme", "industry_theme", 3, f"industry/theme evidence available: {themes}" if themes else "industry/theme evidence available")

    for key, item in risk_lights.items():
        level = item.get("level")
        if level == "red":
            add(f"risk_{key}", "risk", -18, item.get("message") or f"{key} red light")
        elif level == "yellow":
            add(f"risk_{key}", "risk", -2, item.get("message") or f"{key} yellow light", "warning")

    return items


def is_valid_score_number(value) -> bool:
    try:
        value = float(value)
        return math.isfinite(value) and value != 0
    except (TypeError, ValueError):
        return False


def _valid_mv(value) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def _daily_rating(score: int) -> dict:
    if score >= 80:
        return {"level": "A", "text": "重点观察"}
    if score >= 70:
        return {"level": "B", "text": "值得跟踪"}
    if score >= 60:
        return {"level": "C", "text": "谨慎观察"}
    return {"level": "D", "text": "数据或风险约束较多"}

