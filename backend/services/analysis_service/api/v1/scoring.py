"""
A股综合评分 API — 多维度股票评分模型
评分维度: 动量/技术/价值/质量/情绪
所有维度优先使用真实数据，数据不足时明确返回不足原因，不生成随机数据
"""
from datetime import date, datetime
import os

from fastapi import APIRouter, Query, HTTPException, Request

from backend.shared.rate_limit import client_ip, enforce_rate_limit
from backend.services.analysis_service.engine.recommendation_engine import (
    _PRODUCTION_SMALL_CANDIDATE_POOL_WARNING,
    _daily_rating,
    _evaluate_daily_candidate,
    _empty_recommendations_result,
    _evaluate_candidates_parallel,
    _fallback_recommendation_candidates,
    _load_recommendation_candidates,
    _mark_fallback_recommendation,
    _mark_fallback_recommendations,
    _supplement_development_candidates,
    _valid_mv,
    is_valid_score_number,
)
from backend.services.analysis_service.engine.research_pipeline import run_research_pipeline
from backend.services.analysis_service.engine.strategy_config import list_strategy_ids
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


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _query_default(value, fallback):
    """Support direct unit-test calls where FastAPI Query defaults are passed through."""
    default = getattr(value, "default", None)
    if default is not None:
        return default
    return fallback if value is None else value


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
    strategy: str = Query("auto", description="策略: auto/retail_small/value_quality/growth_momentum/reversal_watch/event_driven/dividend_defensive"),
    max_candidates: int = Query(200, ge=20, le=200, description="最大候选评估数"),
    concurrency: int = Query(16, ge=4, le=32, description="并发评估数"),
    include_evidence: bool = Query(True, description="是否返回证据链"),
    include_debate: bool = Query(True, description="是否返回多空反驳"),
    initial_full_scan: bool = Query(False, description="是否显式触发首次全量筛选，默认关闭以避免阻塞首屏"),
):
    """
    获取每日A股观察池 (按综合评分排序)
    """
    market = str(_query_default(market, "ALL"))
    limit = int(_query_default(limit, 10))
    force_refresh = bool(_query_default(force_refresh, False))
    strategy = str(_query_default(strategy, "auto"))
    max_candidates = int(_query_default(max_candidates, 200))
    concurrency = int(_query_default(concurrency, 16))
    include_evidence = bool(_query_default(include_evidence, True))
    include_debate = bool(_query_default(include_debate, True))
    initial_full_scan = bool(_query_default(initial_full_scan, False))

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
    strategy = strategy.strip().lower()
    if strategy not in list_strategy_ids(include_auto=True) and strategy != "quality":
        raise HTTPException(status_code=400, detail="strategy 不受支持")

    from backend.shared.cache import get_cache_manager

    from backend.shared.config import app_env, is_production

    env_name = app_env().lower()
    cache = await get_cache_manager()
    bootstrap_enabled = _bool_env("DAILY_RECOMMENDATIONS_INITIAL_FULL_SCAN", True)
    bootstrap_cap = _int_env("DAILY_RECOMMENDATIONS_INITIAL_FULL_SCAN_MAX", 5000, minimum=200, maximum=6000)
    bootstrap_key = f"bootstrap:v1:{date.today().isoformat()}:{env_name}:{market}:{strategy}"
    bootstrap_state = await cache.get("daily_recommendations", bootstrap_key)
    run_initial_full_scan = bootstrap_enabled and initial_full_scan and limit >= 50 and not bootstrap_state
    candidate_limit = bootstrap_cap if run_initial_full_scan else min(max(max_candidates, limit * 4), 200)
    cache_key = (
        f"v5:{date.today().isoformat()}:{env_name}:{market}:{limit}:{strategy}:"
        f"{candidate_limit}:{concurrency}:{'initial-full-scan' if run_initial_full_scan else 'rotating'}:"
        f"evidence-{int(include_evidence)}:debate-{int(include_debate)}"
    )
    cached = None if force_refresh else await cache.get("daily_recommendations", cache_key)
    if cached:
        cached["cache_hit"] = True
        return cached

    result = await run_research_pipeline(
        market=market,
        limit=limit,
        requested_strategy=strategy,
        candidate_limit=candidate_limit,
        concurrency=concurrency,
        run_initial_full_scan=run_initial_full_scan,
        include_evidence=include_evidence,
        include_debate=include_debate,
        load_candidates=_load_recommendation_candidates,
        fallback_candidates=_fallback_recommendation_candidates,
        supplement_candidates=_supplement_development_candidates,
        evaluate_candidates=_evaluate_candidates_parallel,
        mark_fallback=_mark_fallback_recommendation,
        mark_fallback_batch=_mark_fallback_recommendations,
        empty_result_factory=_empty_recommendations_result,
    )
    result["concurrency"] = concurrency
    result["max_candidates"] = candidate_limit
    result["initial_full_scan"] = {
        "enabled": bootstrap_enabled,
        "used": run_initial_full_scan,
        "status": (
            "completed_this_request"
            if run_initial_full_scan
            else "already_completed"
            if bootstrap_state
            else "not_requested"
            if bootstrap_enabled and limit >= 50
            else "not_required"
        ),
        "scanned_count": result.get("candidate_count", 0) if run_initial_full_scan else int((bootstrap_state or {}).get("scanned_count") or 0),
        "universe_count": result.get("candidate_universe_count", 0) or int((bootstrap_state or {}).get("universe_count") or 0),
        "cap": bootstrap_cap,
        "next_mode": "daily_rotating_200",
    }
    result["cache_hit"] = False
    result["disclaimer"] = "每日观察池仅用于筛选值得继续研究的标的，不是买入建议；需结合个人风险承受能力和完整信息独立判断。"
    if run_initial_full_scan:
        await cache.set(
            "daily_recommendations",
            bootstrap_key,
            value={
                "status": "completed",
                "scanned_count": result.get("candidate_count", 0),
                "universe_count": result.get("candidate_universe_count", 0),
                "completed_at": result["updated_at"],
                "selection": (result.get("selection") or {}).get("mode"),
            },
        )
    await cache.set("daily_recommendations", cache_key, value=result)
    return result
