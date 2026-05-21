"""乘法评分器 — final_score = base × industry_mul × fundamental_mul × momentum_mul"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import text

from backend.shared.database import SessionLocal
from backend.services.analysis_service.engine.industry_scorer import get_industry_health

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


def _env_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _rebalance_by_industry(candidates: list[dict], max_per_industry: int) -> list[dict]:
    if max_per_industry <= 0:
        return candidates

    selected: list[dict] = []
    overflow: list[dict] = []
    counts: dict[str, int] = {}
    for item in candidates:
        industry = str(item.get("industry_name") or item.get("sector") or "UNKNOWN")
        count = counts.get(industry, 0)
        if count < max_per_industry:
            selected.append(item)
            counts[industry] = count + 1
        else:
            overflow.append(item)
    return selected + overflow


def apply_multiplier_scoring(
    candidates: list[dict],
    trade_date: str,
    top_n: int = 20,
    *,
    almost_band: float | None = None,
    almost_min: int | None = None,
    industry_cap: int | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """
    对已有 base_score (anomaly_score) 的候选股应用乘法评分。

    返回 (top_n_list, almost_list, summary)
    almost_list: 差5分以内的近选名单
    """
    if not candidates:
        return [], [], {"status": "no_candidates"}

    db = SessionLocal()
    try:
        symbols = [c["symbol"] for c in candidates]
        fin_map = _load_financial_data(db, symbols)

        for item in candidates:
            base = item.get("anomaly_score") or 0
            ind_mul, ind_detail = _industry_multiplier(item, trade_date)
            fund_mul, fund_detail = _fundamental_multiplier(item, fin_map)
            mom_mul, mom_detail = _momentum_multiplier(item, trade_date)

            final = round(base * ind_mul * fund_mul * mom_mul, 2)

            item["base_score"] = base
            item["final_score"] = final
            item["industry_mul"] = ind_mul
            item["fundamental_mul"] = fund_mul
            item["momentum_mul"] = mom_mul
            item["multiplier_detail"] = {
                "industry": ind_detail,
                "fundamental": fund_detail,
                "momentum": mom_detail,
            }

        candidates.sort(key=lambda x: x["final_score"], reverse=True)
        cap = industry_cap if industry_cap is not None else _env_int("DAILY_POOL_MAX_PER_INDUSTRY", 4, min_value=0, max_value=20)
        ranked_candidates = _rebalance_by_industry(candidates, cap)

        top = ranked_candidates[:top_n]
        threshold = top[-1]["final_score"] if top else 0
        band = almost_band if almost_band is not None else _env_float("DAILY_POOL_ALMOST_SCORE_BAND", 8.0, min_value=0, max_value=30)
        minimum = almost_min if almost_min is not None else _env_int("DAILY_POOL_ALMOST_MIN", 10, min_value=0, max_value=200)
        almost = [c for c in ranked_candidates[top_n:] if c["final_score"] >= threshold - band]
        if len(almost) < minimum:
            symbols = {item.get("symbol") for item in almost}
            for item in ranked_candidates[top_n:top_n + minimum]:
                if item.get("symbol") not in symbols:
                    almost.append(item)
                    symbols.add(item.get("symbol"))

        summary = {
            "status": "ok",
            "total": len(candidates),
            "top_n": len(top),
            "almost_count": len(almost),
            "almost_score_band": band,
            "almost_min": minimum,
            "max_per_industry": cap,
            "score_range": [top[0]["final_score"], top[-1]["final_score"]] if top else [],
        }

        logger.info(
            "Multiplier scoring: %d candidates → top %d (%.1f ~ %.1f), %d almost",
            len(candidates), len(top),
            top[0]["final_score"] if top else 0,
            top[-1]["final_score"] if top else 0,
            len(almost),
        )
        return top, almost, summary

    finally:
        db.close()


def _industry_multiplier(item: dict, trade_date: str) -> tuple[float, dict]:
    """
    行业健康分 → 乘数：
    ≥80 → 1.20, 70-79 → 1.10, 60-69 → 1.00,
    50-59 → 0.85, 40-49 → 0.65, <40 → 0.50
    """
    industry_name = item.get("industry_name") or item.get("sector")
    if not industry_name:
        return 1.0, {"reason": "no_industry_data"}

    health = get_industry_health(industry_name, trade_date)
    if not health:
        return 1.0, {"reason": "no_health_data"}

    score = health.get("health_score", 60)

    if score >= 80:
        mul = 1.20
    elif score >= 70:
        mul = 1.10
    elif score >= 60:
        mul = 1.00
    elif score >= 50:
        mul = 0.85
    elif score >= 40:
        mul = 0.65
    else:
        mul = 0.50

    detail = {
        "health_score": score,
        "raw_mul": mul,
        "is_healthy": health.get("is_healthy"),
    }

    # 逆势反弹额外惩罚
    trend_features = item.get("trend_features") or {}
    stock_5d_gain = trend_features.get("recent_5d_gain") or (item.get("change_pct") or 0)
    if stock_5d_gain > 8 and score < 50:
        mul *= 0.7
        detail["contrarian_penalty"] = True

    return round(mul, 2), detail


def _fundamental_multiplier(item: dict, fin_map: dict) -> tuple[float, dict]:
    """
    连续恶化季度数 → 乘数：
    0季+营收增长 → 1.10, 0-1季 → 1.00, 2季 → 0.85,
    3季 → 0.70, ≥4季 → 0.60
    额外：经营现金流连续为负 → 再×0.90
    """
    symbol = item.get("symbol", "")
    fin = fin_map.get(symbol)
    if not fin:
        return 1.0, {"reason": "no_financial_data"}

    decline_q = max(
        fin.get("revenue_decline_quarters") or 0,
        fin.get("profit_decline_quarters") or 0,
    )

    if decline_q == 0 and (fin.get("revenue_yoy") or 0) > 0.05:
        mul = 1.10
    elif decline_q <= 1:
        mul = 1.00
    elif decline_q == 2:
        mul = 0.85
    elif decline_q == 3:
        mul = 0.70
    else:
        mul = 0.60

    detail = {
        "decline_quarters": decline_q,
        "revenue_yoy": fin.get("revenue_yoy"),
        "profit_yoy": fin.get("profit_yoy"),
    }

    if (fin.get("cashflow_negative_quarters") or 0) >= 2:
        mul *= 0.90
        detail["cashflow_penalty"] = True

    return round(mul, 2), detail


def _momentum_multiplier(item: dict, trade_date: str) -> tuple[float, dict]:
    """
    行业健康度5日变化 → 乘数：
    ≥+10 → 1.15, +5~+9 → 1.05, ±5 → 1.00,
    -5~-15 → 0.85, <-15 → 0.70
    """
    industry_name = item.get("industry_name") or item.get("sector")
    if not industry_name:
        return 1.0, {"reason": "no_industry_data"}

    health = get_industry_health(industry_name, trade_date)
    if not health:
        return 1.0, {"reason": "no_health_data"}

    change = health.get("score_change_5d")
    if change is None:
        return 1.0, {"reason": "no_history"}

    if change >= 10:
        mul = 1.15
    elif change >= 5:
        mul = 1.05
    elif change >= -5:
        mul = 1.00
    elif change >= -15:
        mul = 0.85
    else:
        mul = 0.70

    return round(mul, 2), {"score_change_5d": change}


def _load_financial_data(db, symbols: list[str]) -> dict:
    """加载候选股最新财务趋势数据"""
    if not symbols:
        return {}

    code_map = {}
    for s in symbols:
        code = s.split(".")[0] if "." in s else s
        code_map[code] = s

    codes = list(code_map.keys())
    if not codes:
        return {}

    placeholders = ", ".join(f":c{i}" for i in range(len(codes)))
    params = {f"c{i}": c for i, c in enumerate(codes)}

    try:
        rows = db.execute(
            text(f"""
                SELECT DISTINCT ON (stock_code) stock_code,
                       revenue_decline_quarters, profit_decline_quarters,
                       cashflow_negative_quarters, revenue_yoy, profit_yoy
                FROM financial_trends
                WHERE stock_code IN ({placeholders})
                ORDER BY stock_code, report_date DESC
            """),
            params,
        ).fetchall()
    except Exception:
        return {}

    result = {}
    for row in rows:
        stock_code = row[0]
        symbol = code_map.get(stock_code, stock_code)
        result[symbol] = {
            "revenue_decline_quarters": row[1],
            "profit_decline_quarters": row[2],
            "cashflow_negative_quarters": row[3],
            "revenue_yoy": row[4],
            "profit_yoy": row[5],
        }
    return result
