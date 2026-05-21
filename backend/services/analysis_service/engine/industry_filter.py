"""行业景气度过滤器 — Pipeline 第2.5步，拦截行业恶化中的逆势反弹股"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text

from backend.shared.database import SessionLocal
from backend.services.analysis_service.engine.industry_scorer import get_industry_health
from backend.services.analysis_service.engine.industry_collector import get_industry_for_stock

logger = logging.getLogger(__name__)

INDUSTRY_HEALTH_THRESHOLD = 40
SHADOW_MODE = False


def filter_by_industry(
    candidates: list[dict],
    trade_date: str,
) -> tuple[list[dict], dict]:
    """
    对候选股进行行业景气度过滤。

    返回 (filtered_candidates, summary)
    summary 包含过滤统计信息。
    """
    if not candidates:
        return candidates, {"status": "skipped", "reason": "no_candidates"}

    passed = []
    rejected = []
    no_data = 0
    industry_cache: dict[str, Optional[dict]] = {}

    for item in candidates:
        industry_name = _resolve_industry(item, industry_cache)
        if not industry_name:
            item["industry_filter"] = {"status": "no_data", "pass": True}
            passed.append(item)
            no_data += 1
            continue

        health = get_industry_health(industry_name, trade_date)
        if not health:
            item["industry_filter"] = {"status": "no_health_data", "pass": True}
            passed.append(item)
            no_data += 1
            continue

        industry_check = _evaluate_industry_health(health)
        accel_check = _check_acceleration(health)
        relative_check = _check_relative_strength(item, health, trade_date)

        if not industry_check["pass"] or not accel_check["pass"] or not relative_check["pass"]:
            reasons = industry_check.get("flags", []) + accel_check.get("flags", []) + relative_check.get("flags", [])
            item["industry_filter"] = {
                "status": "rejected",
                "pass": False,
                "industry_name": industry_name,
                "health_score": health["health_score"],
                "reasons": reasons,
            }
            if SHADOW_MODE:
                item["industry_filter"]["shadow_rejected"] = True
                item["industry_filter"]["pass"] = True
                passed.append(item)
            else:
                rejected.append(item)
        else:
            item["industry_filter"] = {
                "status": "passed",
                "pass": True,
                "industry_name": industry_name,
                "health_score": health["health_score"],
                "is_healthy": health["is_healthy"],
            }
            passed.append(item)

    summary = {
        "status": "ok",
        "total": len(candidates),
        "passed": len(passed),
        "rejected": len(rejected),
        "no_data": no_data,
        "shadow_mode": SHADOW_MODE,
    }
    logger.info(
        "Industry filter: %d/%d passed, %d rejected, %d no_data (shadow=%s)",
        len(passed), len(candidates), len(rejected), no_data, SHADOW_MODE,
    )
    return passed, summary


def _resolve_industry(item: dict, cache: dict) -> Optional[str]:
    """解析个股所属行业名称，支持模糊匹配"""
    # 优先从快照数据中获取
    industry_name = item.get("industry_name") or item.get("sector")
    if industry_name:
        matched = _fuzzy_match_industry(industry_name)
        if matched:
            item["industry_name"] = matched
            return matched
        return industry_name

    symbol = item.get("symbol", "")
    if symbol in cache:
        info = cache[symbol]
        return info.get("industry_name") if info else None

    info = get_industry_for_stock(symbol)
    cache[symbol] = info
    if info:
        matched = _fuzzy_match_industry(info["industry_name"])
        if matched:
            item["industry_name"] = matched
            return matched
        item["industry_name"] = info["industry_name"]
        return info["industry_name"]
    return None


_industry_name_cache: Optional[list[str]] = None


def _fuzzy_match_industry(sector: str) -> Optional[str]:
    """将 stocks.sector 模糊匹配到 industry_health_scores 的行业名"""
    global _industry_name_cache
    if _industry_name_cache is None:
        db = SessionLocal()
        try:
            rows = db.execute(
                text("SELECT DISTINCT industry_name FROM industry_health_scores")
            ).fetchall()
            _industry_name_cache = [r[0] for r in rows]
        finally:
            db.close()

    if not _industry_name_cache:
        return None

    # 精确匹配
    if sector in _industry_name_cache:
        return sector

    # 包含匹配：sector 是行业名的子串，或行业名是 sector 的子串
    for name in _industry_name_cache:
        if sector in name or name in sector:
            return name

    # 去掉常见后缀再匹配
    stripped = sector.rstrip("行业设备制造")
    if len(stripped) >= 2:
        for name in _industry_name_cache:
            if stripped in name:
                return name

    return None


def _evaluate_industry_health(health: dict) -> dict:
    """评估行业健康分是否达标"""
    score = health.get("health_score", 100)
    flags = health.get("flags") or []

    if score < INDUSTRY_HEALTH_THRESHOLD:
        return {
            "pass": False,
            "score": score,
            "flags": flags,
            "reason": f"行业健康分{score}分 < 阈值{INDUSTRY_HEALTH_THRESHOLD}",
        }
    return {"pass": True, "score": score, "flags": []}


def _check_acceleration(health: dict) -> dict:
    """行业健康度加速恶化：5日骤降超15分"""
    if health.get("is_accelerating_down"):
        change = health.get("score_change_5d", 0)
        return {
            "pass": False,
            "flags": [f"行业健康度5日骤降{change}分，加速恶化"],
        }
    return {"pass": True, "flags": []}


def _check_relative_strength(item: dict, health: dict, trade_date: str) -> dict:
    """
    个股 vs 行业相对强度检查。
    拦截：个股逆势大涨但行业整体恶化的情况。
    """
    flags = []

    # 个股近5日涨幅
    trend_features = item.get("trend_features") or {}
    stock_5d_gain = trend_features.get("recent_5d_gain")
    if stock_5d_gain is None:
        stock_5d_gain = item.get("change_pct") or 0

    # 行业健康分中的动量和趋势
    health_score = health.get("health_score", 100)
    health_flags = health.get("flags") or []

    # 红牌：个股5日涨>8% 但行业健康分<40（严重恶化）
    if stock_5d_gain > 8 and health_score < 40:
        flags.append(f"逆势反弹：个股5日涨{stock_5d_gain:.1f}%，行业健康分仅{health_score}")
        return {"pass": False, "flags": flags}

    # 黄牌：个股5日涨>5% 但行业有"整体下跌中的反弹"标签
    if stock_5d_gain > 5 and "行业整体下跌中的反弹" in health_flags:
        flags.append(f"行业反弹中的个股：5日涨{stock_5d_gain:.1f}%，行业处于下跌反弹")
        return {"pass": False, "flags": flags}

    return {"pass": True, "flags": []}
