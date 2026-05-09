"""Daily recommendation candidate pool and scoring helpers."""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime
from typing import Optional

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
        "scored_count": 0,
        "concurrency": concurrency,
        "max_candidates": candidate_limit,
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


def _load_recommendation_candidates(market: str, sample_size: int) -> list[dict]:
    from backend.shared.database import SessionLocal
    from backend.shared.models import Stock

    result = []
    seen = set()

    def add(row: dict) -> None:
        code = (row.get("symbol") or "")[:6]
        if not code or code in seen:
            return
        row_market = row.get("market") or ("SH" if code.startswith(("6", "9")) else "SZ")
        if row_market not in ("SH", "SZ"):
            return
        if market != "ALL" and row_market != market:
            return
        name = row.get("name") or code
        if "退" in name or name.startswith(("*ST", "ST")):
            return
        seen.add(code)
        result.append({
            "symbol": f"{code}.{row_market}",
            "name": name,
            "market": row_market,
            "sector": row.get("sector") or "",
        })

    db = SessionLocal()
    try:
        markets = [market] if market in ("SH", "SZ") else ["SH", "SZ"]
        per_market = max(10, sample_size // len(markets))
        for m in markets:
            rows = (
                db.query(Stock)
                .filter(Stock.is_active == True, Stock.market == m)
                .order_by(Stock.id.asc())
                .limit(per_market * 3)
                .all()
            )
            sector_seen = set()
            for row in rows:
                if len(result) >= sample_size:
                    break
                sector = row.sector or ""
                # Keep the candidate pool broad instead of letting one sector dominate.
                if sector and sector in sector_seen and len(sector_seen) >= 8:
                    continue
                add({
                    "symbol": row.symbol,
                    "name": row.name,
                    "market": row.market,
                    "sector": sector,
                })
                if sector:
                    sector_seen.add(sector)
        return result
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
            "industry_themes": [t.get("theme") for t in (industry.get("themes") or [])[:3] if t.get("theme")],
            "updated_at": datetime.now().isoformat(),
        }
    except Exception as exc:
        logger.debug("daily candidate evaluation failed for %s: %s", row.get("symbol"), exc)
        return None


def _score_daily_candidate(stock_data: dict, risk_lights: dict, strategy: str = "retail_small") -> tuple[int, list[str], list[str]]:
    quote = stock_data.get("quote") or {}
    financial = stock_data.get("financial") or {}
    kline = stock_data.get("kline_data") or []
    sentiment = stock_data.get("news_sentiment") or {}
    industry = stock_data.get("industry_event_context") or {}
    readiness = stock_data.get("readiness") or {}
    data_grade = (readiness.get("data_grade") or {}).get("grade", "D")

    score = 50.0
    reasons: list[str] = []
    risk_flags: list[str] = []

    price = float(stock_data.get("price") or 0)
    total_mv = financial.get("total_mv") or quote.get("total_mv")
    circ_mv = financial.get("circ_mv") or quote.get("circ_mv")

    if strategy == "retail_small":
        if price <= 0:
            score -= 25
            risk_flags.append("价格不可用")
        elif price < 3:
            score -= 16
            risk_flags.append("价格过低，需警惕退市或基本面风险")
        elif 5 <= price <= 35:
            score += 14
            reasons.append(f"单手成本约{price * 100:.0f}元，散户更容易分批配置")
        elif 35 < price <= 60:
            score += 6
            reasons.append(f"单手成本约{price * 100:.0f}元，仍在可观察区间")
        elif price > 80:
            score -= 18
            risk_flags.append(f"股价{price:.2f}元，单手成本偏高，不符合散户友好筛选")

        mv = _valid_mv(total_mv) or _valid_mv(circ_mv)
        if mv:
            yi = mv / 1e8
            if 30 <= yi <= 500:
                score += 10
                reasons.append(f"市值约{yi:.0f}亿元，偏小中盘观察范围")
            elif yi < 20:
                score -= 8
                risk_flags.append("市值过小，流动性和波动风险更高")
            elif yi > 1500:
                score -= 14
                risk_flags.append("市值偏大，不符合小而美筛选")
        else:
            score -= 3
            risk_flags.append("市值字段缺失，小而美判断不完整")

    if data_grade == "A":
        score += 12
        reasons.append("数据较完整，适合继续深入研究")
    elif data_grade == "B":
        score += 7
        reasons.append("行情/K线可用，部分基本面或消息面数据可参考")
    elif data_grade == "C":
        score += 2
        risk_flags.append("仅行情和K线较可用，基本面不足")

    if len(kline) >= 20:
        closes = [float(x.get("close") or 0) for x in kline if x.get("close") is not None]
        volumes = [float(x.get("volume") or 0) for x in kline if x.get("volume") is not None]
        if len(closes) >= 20:
            ret5 = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] else 0
            ret20 = (closes[-1] - closes[-20]) / closes[-20] * 100 if closes[-20] else 0
            ma20 = sum(closes[-20:]) / 20
            if closes[-1] >= ma20 and -3 <= ret5 <= 12 and ret20 > -8:
                score += 13
                reasons.append(f"技术面相对稳健：5日{ret5:+.1f}%，20日{ret20:+.1f}%")
            elif ret5 > 18:
                score -= 8
                risk_flags.append("短期涨幅过快，追高风险较高")
            elif ret20 < -15:
                score -= 6
                risk_flags.append("20日趋势偏弱")
        if len(volumes) >= 10 and sum(volumes[-10:-5]) > 0:
            recent_vol = sum(volumes[-5:]) / 5
            prev_vol = sum(volumes[-10:-5]) / 5
            if 1.15 <= recent_vol / prev_vol <= 2.8:
                score += 5
                reasons.append("近5日成交活跃度温和提升")

    pe = financial.get("pe_ttm") or quote.get("pe_ttm")
    pb = financial.get("pb") or quote.get("pb")
    if is_valid_score_number(pe) and is_valid_score_number(pb):
        pe = float(pe)
        pb = float(pb)
        if pe > 0 and pe <= 35 and pb <= 5:
            score += 10
            reasons.append(f"估值字段可用：PE {pe:.1f}，PB {pb:.2f}")
        elif pe <= 0 or pe > 80 or pb > 10:
            score -= 8
            risk_flags.append("PE/PB显示估值或盈利质量需谨慎")
    else:
        score -= 4
        risk_flags.append("PE/PB缺失，估值无法判断")

    if financial:
        revenue_yoy = financial.get("revenue_yoy")
        profit_yoy = financial.get("net_profit_yoy")
        operating_cf = financial.get("operating_cf")
        if is_valid_score_number(revenue_yoy) and float(revenue_yoy) > 0:
            score += 4
            reasons.append(f"营收同比为正：{float(revenue_yoy):.1f}%")
        if is_valid_score_number(profit_yoy) and float(profit_yoy) > 0:
            score += 6
            reasons.append(f"归母净利润同比为正：{float(profit_yoy):.1f}%")
        if operating_cf is not None and float(operating_cf) < 0:
            score -= 5
            risk_flags.append("经营现金流为负")
    else:
        score -= 5
        risk_flags.append("财务数据缺失")

    weighted = sentiment.get("weighted_dominant_sentiment")
    if weighted in ("正面", "positive"):
        score += 5
        reasons.append("新闻加权情绪偏正面")
    elif weighted in ("负面", "negative"):
        score -= 8
        risk_flags.append(sentiment.get("validation_note") or "新闻加权情绪偏负面")

    if industry.get("available"):
        score += 3
        themes = "、".join(t.get("theme", "") for t in (industry.get("themes") or [])[:2] if t.get("theme"))
        if themes:
            reasons.append(f"行业/社会事件线索：{themes}")

    for key, item in risk_lights.items():
        level = item.get("level")
        if level == "red":
            score -= 18
            risk_flags.append(item.get("message") or f"{key}红灯")
        elif level == "yellow":
            score -= 2

    score = int(max(0, min(100, round(score))))
    if not reasons:
        reasons.append("综合数据未出现明显排除项，但仍需进一步研究")
    if not risk_flags:
        risk_flags.append("未发现明显红灯，但仍需关注市场波动")
    return score, reasons, risk_flags


def _build_score_breakdown(stock_data: dict, risk_lights: dict, strategy: str = "retail_small") -> list[dict]:
    quote = stock_data.get("quote") or {}
    financial = stock_data.get("financial") or {}
    kline = stock_data.get("kline_data") or []
    sentiment = stock_data.get("news_sentiment") or {}
    industry = stock_data.get("industry_event_context") or {}
    readiness = stock_data.get("readiness") or {}
    data_grade = (readiness.get("data_grade") or {}).get("grade", "D")

    items: list[dict] = [{"key": "base", "label": "基础分", "delta": 50, "status": "neutral", "message": "进入沪深A股候选池后的基础观察分"}]

    def add(key: str, label: str, delta: int, message: str, status: str | None = None) -> None:
        if status is None:
            status = "positive" if delta > 0 else "negative" if delta < 0 else "neutral"
        items.append({"key": key, "label": label, "delta": delta, "status": status, "message": message})

    price = float(stock_data.get("price") or 0)
    total_mv = financial.get("total_mv") or quote.get("total_mv")
    circ_mv = financial.get("circ_mv") or quote.get("circ_mv")

    if strategy == "retail_small":
        if price <= 0:
            add("retail_affordability", "单手成本", -25, "价格不可用，不能判断散户友好程度")
        elif price < 3:
            add("retail_affordability", "单手成本", -16, "价格过低，需警惕退市或基本面风险")
        elif 5 <= price <= 35:
            add("retail_affordability", "单手成本", 14, f"单手成本约{price * 100:.0f}元，适合分批观察")
        elif 35 < price <= 60:
            add("retail_affordability", "单手成本", 6, f"单手成本约{price * 100:.0f}元，仍在可观察区间")
        elif price > 80:
            add("retail_affordability", "单手成本", -18, f"股价{price:.2f}元，单手成本偏高")
        else:
            add("retail_affordability", "单手成本", 0, f"股价{price:.2f}元，不加分也不排除")

        mv = _valid_mv(total_mv) or _valid_mv(circ_mv)
        if mv:
            yi = mv / 1e8
            if 30 <= yi <= 500:
                add("market_cap", "市值", 10, f"市值约{yi:.0f}亿元，处于小中盘观察范围")
            elif yi < 20:
                add("market_cap", "市值", -8, "市值过小，流动性和波动风险更高")
            elif yi > 1500:
                add("market_cap", "市值", -14, "市值偏大，不符合小而美筛选")
            else:
                add("market_cap", "市值", 0, f"市值约{yi:.0f}亿元，保持中性")
        else:
            add("market_cap", "市值", -3, "市值字段缺失，小而美判断不完整")

    if data_grade == "A":
        add("data_quality", "数据质量", 12, "行情、K线、估值或基本面数据较完整")
    elif data_grade == "B":
        add("data_quality", "数据质量", 7, "行情/K线可用，部分基本面或消息面数据可参考")
    elif data_grade == "C":
        add("data_quality", "数据质量", 2, "基础行情可用，但基本面完整度不足", "warning")
    else:
        add("data_quality", "数据质量", 0, "数据完整度不足，未加分", "warning")

    if len(kline) >= 20:
        closes = [float(x.get("close") or 0) for x in kline if x.get("close") is not None]
        volumes = [float(x.get("volume") or 0) for x in kline if x.get("volume") is not None]
        if len(closes) >= 20:
            ret5 = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] else 0
            ret20 = (closes[-1] - closes[-20]) / closes[-20] * 100 if closes[-20] else 0
            ma20 = sum(closes[-20:]) / 20
            if closes[-1] >= ma20 and -3 <= ret5 <= 12 and ret20 > -8:
                add("technical", "技术走势", 13, f"5日{ret5:+.1f}%，20日{ret20:+.1f}%，走势相对稳健")
            elif ret5 > 18:
                add("technical", "技术走势", -8, "短期涨幅过快，追高风险较高")
            elif ret20 < -15:
                add("technical", "技术走势", -6, "20日趋势偏弱")
            else:
                add("technical", "技术走势", 0, f"5日{ret5:+.1f}%，20日{ret20:+.1f}%，趋势中性")
        if len(volumes) >= 10 and sum(volumes[-10:-5]) > 0:
            recent_vol = sum(volumes[-5:]) / 5
            prev_vol = sum(volumes[-10:-5]) / 5
            ratio = recent_vol / prev_vol if prev_vol else 0
            if 1.15 <= ratio <= 2.8:
                add("volume", "成交活跃度", 5, "近5日成交活跃度温和提升")
    else:
        add("technical", "技术走势", 0, "K线不足20条，技术走势不加分", "warning")

    pe = financial.get("pe_ttm") or quote.get("pe_ttm")
    pb = financial.get("pb") or quote.get("pb")
    if is_valid_score_number(pe) and is_valid_score_number(pb):
        pe_float = float(pe)
        pb_float = float(pb)
        if pe_float > 0 and pe_float <= 35 and pb_float <= 5:
            add("valuation", "估值", 10, f"PE {pe_float:.1f}，PB {pb_float:.2f}，估值字段可用")
        elif pe_float <= 0 or pe_float > 80 or pb_float > 10:
            add("valuation", "估值", -8, "PE/PB显示估值或盈利质量需谨慎")
        else:
            add("valuation", "估值", 0, f"PE {pe_float:.1f}，PB {pb_float:.2f}，估值保持中性")
    else:
        add("valuation", "估值", -4, "PE/PB缺失，估值无法判断")

    if financial:
        revenue_yoy = financial.get("revenue_yoy")
        profit_yoy = financial.get("net_profit_yoy")
        operating_cf = financial.get("operating_cf")
        if is_valid_score_number(revenue_yoy) and float(revenue_yoy) > 0:
            add("financial_revenue", "财务", 4, f"营收同比为正：{float(revenue_yoy):.1f}%")
        if is_valid_score_number(profit_yoy) and float(profit_yoy) > 0:
            add("financial_profit", "财务", 6, f"归母净利润同比为正：{float(profit_yoy):.1f}%")
        if operating_cf is not None and float(operating_cf) < 0:
            add("financial_cashflow", "现金流", -5, "经营现金流为负")
    else:
        add("financial", "财务", -5, "财务数据缺失")

    weighted = sentiment.get("weighted_dominant_sentiment")
    if weighted in ("正面", "positive"):
        add("news_sentiment", "新闻情绪", 5, "新闻加权情绪偏正面")
    elif weighted in ("负面", "negative"):
        add("news_sentiment", "新闻情绪", -8, sentiment.get("validation_note") or "新闻加权情绪偏负面")
    else:
        add("news_sentiment", "新闻情绪", 0, "新闻情绪中性或样本不足")

    if industry.get("available"):
        themes = "、".join(t.get("theme", "") for t in (industry.get("themes") or [])[:2] if t.get("theme"))
        add("industry_events", "行业/社会事件", 3, f"存在可跟踪事件线索：{themes or '行业事件'}")

    red_count = 0
    yellow_count = 0
    for key, item in risk_lights.items():
        level = item.get("level")
        if level == "red":
            red_count += 1
            add(f"risk_{key}", "风险灯", -18, item.get("message") or f"{key}红灯")
        elif level == "yellow":
            yellow_count += 1
            add(f"risk_{key}", "风险灯", -2, item.get("message") or f"{key}黄灯", "warning")
    if red_count == 0 and yellow_count == 0:
        add("risk_lights", "风险灯", 0, "未发现明显红灯或黄灯")

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

