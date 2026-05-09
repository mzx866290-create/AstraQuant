"""
A股综合评分 API — 多维度股票评分模型
评分维度: 动量/技术/价值/质量/情绪
所有维度优先使用真实数据，数据不足时明确返回不足原因，不生成随机数据
"""
from datetime import date, datetime

from fastapi import APIRouter, Query, HTTPException, Request

from backend.shared.rate_limit import client_ip, enforce_rate_limit
from backend.services.analysis_service.engine.recommendation_engine import (
    _PRODUCTION_SMALL_CANDIDATE_POOL_WARNING,
    _build_score_breakdown,
    _daily_rating,
    _empty_recommendations_result,
    _evaluate_candidates_parallel,
    _evaluate_daily_candidate,
    _fallback_recommendation_candidates,
    _load_recommendation_candidates,
    _mark_fallback_recommendation,
    _mark_fallback_recommendations,
    _score_daily_candidate,
    _supplement_development_candidates,
    _valid_mv,
    is_valid_score_number,
)
from backend.services.analysis_service.engine.scoring_calculations import (
    compute_momentum as _compute_momentum,
    compute_quality as _compute_quality,
    compute_sentiment as _compute_sentiment,
    compute_technical as _compute_technical,
    compute_value as _compute_value,
    to_rating as _to_rating,
)
from backend.services.analysis_service.engine.scoring_data import (
    MONEY_FLOW_CIRCUIT_OPEN_WARNING as _MONEY_FLOW_CIRCUIT_OPEN_WARNING,
    MONEY_FLOW_EMPTY_WARNING as _MONEY_FLOW_EMPTY_WARNING,
    MONEY_FLOW_SOURCE_ERROR_WARNING as _MONEY_FLOW_SOURCE_ERROR_WARNING,
    MONEY_FLOW_UNAVAILABLE_WARNING as _MONEY_FLOW_UNAVAILABLE_WARNING,
    build_money_flow_context as _build_money_flow_context,
    fetch_financial_reports as _fetch_financial_reports,
    fetch_money_flow as _fetch_money_flow,
    fetch_recent_kline as _fetch_recent_kline,
    fetch_recent_news as _fetch_recent_news,
    float_env as _float_env,
    kline_breakers as _kline_breakers,
    money_flow_breaker as _money_flow_breaker,
)

router = APIRouter(tags=["综合评分"])


# ── API ──


@router.get("/{symbol}")
async def get_stock_score(symbol: str, request: Request = None):
    """
    A股综合评分 (10分制) — 全部使用真实计算

    评分维度:
    - **动量评分** (30%): 短/中/长期涨跌幅趋势
    - **技术评分** (25%): MACD/RSI/KDJ/BOLL多指标综合
    - **价值评分** (20%): PE/PB相对估值
    - **质量评分** (15%): ROE/毛利率/净利润增速+F-Score
    - **情绪评分** (10%): 新闻情感+资金流向+换手率变化
    """
    if request is not None:
        ip = client_ip(request)
        normalized_symbol = symbol.strip().upper()
        await enforce_rate_limit(scope="score:symbol:ip", identity=ip, limit=60, window_seconds=60, fail_closed=False)
        await enforce_rate_limit(
            scope="score:symbol:ip_symbol",
            identity=f"{ip}:{normalized_symbol}",
            limit=10,
            window_seconds=60,
            fail_closed=False,
        )

    try:
        kline_data = await _fetch_recent_kline(symbol, 200)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"K线数据源不可用: {e}")
    if len(kline_data) < 20:
        raise HTTPException(status_code=404, detail="K线数据不足，至少需要20条")

    financial_reports = _fetch_financial_reports(symbol)
    news_list = _fetch_recent_news(symbol, 7)
    money_flow = await _fetch_money_flow(symbol, 20)

    momentum = _compute_momentum(kline_data)
    technical = _compute_technical(kline_data)
    value = _compute_value(kline_data, financial_reports)
    quality = _compute_quality(kline_data, financial_reports)
    sentiment = _compute_sentiment(kline_data, news_list, money_flow)

    total = round(
        momentum["score"] * 0.30 +
        technical["score"] * 0.25 +
        value["score"] * 0.20 +
        quality["score"] * 0.15 +
        sentiment["score"] * 0.10,
        2,
    )

    return {
        "symbol": symbol,
        "total_score": total,
        "rating": _to_rating(total),
        "dimensions": {
            "momentum": {"score": momentum["score"], "weight": 0.30,
                         "label": "动量评分", "detail": momentum["detail"]},
            "technical": {"score": technical["score"], "weight": 0.25,
                          "label": "技术评分", "detail": technical["detail"]},
            "value": {"score": value["score"], "weight": 0.20,
                      "label": "价值评分", "detail": value["detail"]},
            "quality": {"score": quality["score"], "weight": 0.15,
                        "label": "质量评分", "detail": quality["detail"]},
            "sentiment": {"score": sentiment["score"], "weight": 0.10,
                          "label": "情绪评分", "detail": sentiment["detail"],
                          "status": sentiment.get("status", "insufficient"),
                          "source": sentiment.get("source", "insufficient"),
                          "warnings": sentiment.get("warnings", [])},
        },
        "data_source_summary": {
            "momentum_source": "kline",
            "technical_source": "indicators",
            "value_source": value.get("source", "estimated"),
            "quality_source": quality.get("source", "estimated"),
            "sentiment_source": sentiment.get("source", "insufficient"),
            "money_flow_source": money_flow.get("source", "unknown"),
            "money_flow_status": money_flow.get("status", "unknown"),
        },
        "data_quality": {
            "money_flow": money_flow.get("data_quality", {}),
            "sentiment": {
                "status": sentiment.get("status", "insufficient"),
                "warnings": sentiment.get("warnings", []),
            },
        },
        "warnings": sentiment.get("warnings", []),
        "updated_at": datetime.now().isoformat(),
    }


@router.get("/batch/recommend")
async def get_recommendations(
    request: Request = None,
    market: str = Query("ALL", description="市场: ALL/SH/SZ"),
    limit: int = Query(10, ge=5, le=50, description="观察池数量"),
    force_refresh: bool = Query(False, description="跳过当天缓存重新计算"),
    strategy: str = Query("retail_small", description="策略: retail_small/quality"),
    max_candidates: int = Query(50, ge=20, le=120, description="最大候选评估数"),
    concurrency: int = Query(16, ge=4, le=32, description="并发评估数"),
):
    """
    获取每日A股观察池 (按综合评分排序)
    """
    if request is not None:
        ip = client_ip(request)
        await enforce_rate_limit(scope="score:recommend:ip", identity=ip, limit=10, window_seconds=60, fail_closed=False)
        if force_refresh:
            await enforce_rate_limit(
                scope="score:recommend:force_refresh:ip",
                identity=ip,
                limit=2,
                window_seconds=60,
                fail_closed=False,
            )

    market = market.upper()
    if market not in ("ALL", "SH", "SZ"):
        raise HTTPException(status_code=400, detail="market 仅支持 ALL/SH/SZ")
    if strategy not in ("retail_small", "quality"):
        raise HTTPException(status_code=400, detail="strategy 仅支持 retail_small/quality")

    from backend.shared.cache import get_cache_manager

    from backend.shared.config import app_env, is_production

    candidate_limit = min(max(max_candidates, limit * 4), 120)
    env_name = app_env().lower()
    cache_key = f"v3:{date.today().isoformat()}:{env_name}:{market}:{limit}:{strategy}:{candidate_limit}:{concurrency}"
    cache = await get_cache_manager()
    cached = None if force_refresh else await cache.get("daily_recommendations", cache_key)
    if cached:
        cached["cache_hit"] = True
        return cached

    candidates = _load_recommendation_candidates(market, candidate_limit)
    candidate_source = "db"
    fallback_codes: set[str] = set()
    warnings: list[str] = []
    if not candidates:
        if is_production():
            result = _empty_recommendations_result(
                market=market,
                strategy=strategy,
                candidate_limit=candidate_limit,
                concurrency=concurrency,
                warnings=["recommendation candidate pool is empty; no recommendations are available"],
            )
            await cache.set("daily_recommendations", cache_key, value=result)
            return result

        candidates, candidate_source, warnings, fallback_codes = _supplement_development_candidates(
            candidates,
            _fallback_recommendation_candidates(market),
            candidate_limit,
        )
    elif is_production() and len(candidates) < limit:
        warnings.append(_PRODUCTION_SMALL_CANDIDATE_POOL_WARNING)
    elif not is_production() and len(candidates) < candidate_limit:
        candidates, candidate_source, warnings, fallback_codes = _supplement_development_candidates(
            candidates,
            _fallback_recommendation_candidates(market),
            candidate_limit,
        )

    scored = await _evaluate_candidates_parallel(candidates, strategy, concurrency=concurrency)
    if candidate_source == "fallback":
        scored = [_mark_fallback_recommendation(item) for item in scored]
    elif candidate_source == "mixed":
        scored = _mark_fallback_recommendations(scored, fallback_codes)
    scored.sort(key=lambda x: (x["score"], x["data_grade"].get("grade") == "A", -len(x.get("risk_flags", []))), reverse=True)

    recommendations = scored[:limit]
    if is_production() and len(recommendations) < limit and _PRODUCTION_SMALL_CANDIDATE_POOL_WARNING not in warnings:
        warnings.append(_PRODUCTION_SMALL_CANDIDATE_POOL_WARNING)
    result = {
        "recommendations": recommendations,
        "market": market,
        "status": "ok",
        "candidate_source": candidate_source,
        "warnings": warnings,
        "count": len(recommendations),
        "candidate_count": len(candidates),
        "scored_count": len(scored),
        "concurrency": concurrency,
        "max_candidates": candidate_limit,
        "cache_hit": False,
        "updated_at": datetime.now().isoformat(),
        "method": {
            "name": "daily_observation_pool_v1",
            "description": "基于公开行情/K线、估值、财务、新闻情绪、行业事件和数据质量生成每日观察池，不构成买卖建议。",
            "strategy": strategy,
            "strategy_label": "散户小而美" if strategy == "retail_small" else "质量优先",
            "weights": {
                "base": 50,
                "quote_quality": 15,
                "technical": 25,
                "valuation": 20,
                "financial": 20,
                "news_and_industry": 10,
                "retail_affordability": 20 if strategy == "retail_small" else 0,
                "risk_penalty": -30,
            },
        },
        "disclaimer": "每日观察池仅用于筛选值得继续研究的标的，不是买入建议；需结合个人风险承受能力和完整信息独立判断。",
    }
    await cache.set("daily_recommendations", cache_key, value=result)
    return result
