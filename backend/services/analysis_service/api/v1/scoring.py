"""
A股综合评分 API — 多维度股票评分模型
评分维度: 动量/技术/价值/质量/情绪
所有维度优先使用真实数据，数据不足时明确返回不足原因，不生成随机数据
"""
from datetime import date, datetime, timedelta
import asyncio
import logging
import os

from fastapi import APIRouter, Query, HTTPException, Request

from backend.shared.rate_limit import client_ip, enforce_rate_limit
from backend.services.analysis_service.engine.recommendation_engine import (
    _build_score_breakdown,
    _daily_rating,
    _evaluate_candidates_parallel,
    _fallback_recommendation_candidates,
    _load_recommendation_candidates,
    _score_daily_candidate,
    is_valid_score_number,
)
from backend.services.analysis_service.engine.ai_analysis_data import clean_symbol, get_stock_data
from backend.services.analysis_service.engine.ai_analysis_fallbacks import build_risk_lights
from backend.services.analysis_service.engine.context_builder import context_builder
from backend.services.analysis_service.engine.debate_engine import build_debate_view
from backend.services.analysis_service.engine.evidence_chain import build_evidence_chain
from backend.services.analysis_service.engine.market_regime import detect_market_regime
from backend.services.analysis_service.engine.risk_veto import evaluate_risk_veto
from backend.services.analysis_service.engine.strategy_config import list_strategy_ids, resolve_strategy
from backend.services.analysis_service.engine.strategy_scoring import apply_strategy_weighted_score
from backend.services.analysis_service.engine.theme_validation import build_theme_validation
from backend.services.analysis_service.engine.observation_pool_optimizer import (
    fetch_review_feedback_for_symbols,
    optimize_observation_pool,
)
from backend.services.analysis_service.engine.intraday_confirmation import build_intraday_confirmation
from backend.services.analysis_service.engine.research_pipeline import run_research_pipeline as _engine_run_research_pipeline
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
logger = logging.getLogger(__name__)
RECOMMENDATION_CACHE_VERSION = "v4"


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


def _next_weekday(value: date) -> date:
    candidate = value + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _observation_target_date(data_date: str | None) -> str | None:
    if not data_date:
        return None
    try:
        return _next_weekday(date.fromisoformat(data_date)).isoformat()
    except ValueError:
        return None


def _has_news_impact(row) -> bool:
    return bool(_news_impact_items(row))


def _news_impact_items(row) -> list[dict]:
    chain = row.evidence_chain_json or []
    if not isinstance(chain, list):
        return []
    return [item for item in chain if isinstance(item, dict) and item.get("factor") == "news_impact_agent"]


def _is_recovery_pool(rows: list) -> bool:
    return any(getattr(row, "strategy_id", None) == "snapshot_fast_recovery" for row in rows or [])


def _prefer_formal_pool(query, model):
    formal_query = query.filter(model.strategy_id != "snapshot_fast_recovery")
    return formal_query if formal_query.first() is not None else query


def _observation_bucket_from_factor_snapshot(factor_snapshot) -> str:
    if isinstance(factor_snapshot, list):
        return "trend_strength"
    if not isinstance(factor_snapshot, dict):
        return "trend_strength"
    return str(factor_snapshot.get("observation_bucket") or "trend_strength")


def _priority_from_factor_snapshot(factor_snapshot) -> int:
    if isinstance(factor_snapshot, list):
        return 0
    if not isinstance(factor_snapshot, dict):
        return 0
    try:
        return int(float(factor_snapshot.get("priority_score") or 0))
    except (TypeError, ValueError):
        return 0


def _tier_rank_from_factor_snapshot(factor_snapshot) -> int:
    if isinstance(factor_snapshot, list):
        return 2
    if not isinstance(factor_snapshot, dict):
        return 2
    return {"A": 0, "B": 1, "C": 2}.get(str(factor_snapshot.get("tier") or "C"), 2)


def _rebalance_rows_by_observation_bucket(rows: list, limit: int) -> list:
    if not rows:
        return []
    caps = {
        "trend_strength": max(1, int(limit * 0.65)),
        "pullback_support": max(1, int(limit * 0.30)),
        "oversold_reversal": max(1, int(limit * 0.20)),
    }
    selected = []
    overflow = []
    counts: dict[str, int] = {}
    for row in rows:
        bucket = _observation_bucket_from_factor_snapshot(row.factor_snapshot_json)
        count = counts.get(bucket, 0)
        if count < caps.get(bucket, limit):
            selected.append(row)
            counts[bucket] = count + 1
        else:
            overflow.append(row)
    rebalanced = (selected + overflow)[:limit]
    return sorted(
        rebalanced,
        key=lambda row: (
            _tier_rank_from_factor_snapshot(row.factor_snapshot_json),
            -_priority_from_factor_snapshot(row.factor_snapshot_json),
            -float(row.score or 0),
        ),
    )


async def _ensure_observation_pool_optimizer(result: dict) -> dict:
    result = _prepare_internal_optimizer_fields(result)
    recommendations = result.get("recommendations") or []
    if not recommendations:
        return result

    market_regime = result.get("market_regime") or {}
    try:
        already_optimized = any(isinstance(rec.get("pool_optimizer"), dict) for rec in recommendations)
        stale_optimizer = any(
            _recommendation_has_news_impact(rec)
            and not (((rec.get("pool_optimizer") or {}).get("news") or {}).get("has_news"))
            for rec in recommendations
        )
        if already_optimized and not stale_optimizer:
            try:
                from backend.services.analysis_service.engine.pool_summary_generator import generate_pool_summary

                result["pool_summary"] = generate_pool_summary(recommendations, market_regime)
            except Exception as exc:
                logger.debug("pool summary regeneration failed for existing optimizer: %s", exc)
            return _strip_internal_response_fields(result)

        symbols = [str(rec.get("symbol") or "") for rec in recommendations]
        review_feedback = await asyncio.to_thread(fetch_review_feedback_for_symbols, symbols)
        optimized, optimizer_summary = optimize_observation_pool(
            recommendations,
            market_regime,
            mode="response",
            review_feedback=review_feedback,
        )
        result["recommendations"] = optimized
        result["count"] = len(optimized)
        pool_summary = result.get("pool_summary") or {}
        try:
            from backend.services.analysis_service.engine.pool_summary_generator import generate_pool_summary

            pool_summary = generate_pool_summary(optimized, market_regime)
        except Exception as exc:
            logger.debug("pool summary regeneration failed in response optimizer: %s", exc)
        pool_summary["optimizer"] = optimizer_summary
        result["pool_summary"] = pool_summary
    except Exception as exc:
        logger.debug("observation pool optimizer response enrichment failed: %s", exc)
    return _strip_internal_response_fields(result)


def _recommendation_has_news_impact(rec: dict) -> bool:
    if rec.get("_news_impact_items"):
        return True
    chain = rec.get("evidence_chain") or []
    if not isinstance(chain, list):
        return False
    return any(isinstance(item, dict) and item.get("factor") == "news_impact_agent" for item in chain)


def _prepare_internal_optimizer_fields(result: dict) -> dict:
    for rec in result.get("recommendations") or []:
        if not isinstance(rec, dict):
            continue
        internal_news = rec.get("_news_impact_items") or []
        if internal_news and not rec.get("evidence_chain"):
            rec["evidence_chain"] = internal_news
            rec["_internal_evidence_chain_added"] = True
    return result


def _strip_internal_response_fields(result: dict) -> dict:
    for rec in result.get("recommendations") or []:
        if isinstance(rec, dict):
            if rec.pop("_internal_evidence_chain_added", False):
                rec["evidence_chain"] = []
            rec.pop("_news_impact_items", None)
    return result


def _pool_phase_metadata(
    *,
    data_date: str | None,
    target_date: str | None,
    pipeline_status: str,
    rows: list,
    now: datetime | None = None,
) -> dict:
    if not rows or not data_date:
        return {
            "pool_phase": "empty",
            "pool_phase_label": "暂无观察池",
            "pool_phase_message": "当前还没有可用的每日观察池。",
            "news_enriched_count": 0,
        }

    now = now or datetime.now()
    today = now.date()
    data_day = date.fromisoformat(data_date)
    target_day = date.fromisoformat(target_date) if target_date else _next_weekday(data_day)
    enriched_count = sum(1 for row in rows if _has_news_impact(row))
    is_recovery = _is_recovery_pool(rows)
    weekend = today.weekday() >= 5

    if is_recovery:
        return {
            "pool_phase": "recovery_enriched" if enriched_count else "recovery_base",
            "pool_phase_label": "应急恢复池",
            "pool_phase_message": (
                f"当前观察池基于 {data_date} 收盘快照应急恢复生成"
                f"{'，已完成资讯影响增强' if enriched_count else '，资讯影响增强尚未完成'}；"
                "可用于临时观察，但仍需等待完整评分流水线复核。"
            ),
            "news_enriched_count": enriched_count,
            "pool_recovery": True,
            "pool_recovery_reason": "snapshot_fast_recovery",
        }

    if pipeline_status == "stale" and today > target_day:
        return {
            "pool_phase": "stale",
            "pool_phase_label": "沿用旧观察池",
            "pool_phase_message": f"当前沿用基于 {data_date} 收盘数据生成的观察池，等待下一次交易日盘后更新。",
            "news_enriched_count": enriched_count,
        }

    if weekend and today < target_day:
        return {
            "pool_phase": "weekend_base",
            "pool_phase_label": "周末基础观察池",
            "pool_phase_message": f"周末休市期间沿用基于 {data_date} 收盘数据生成的基础观察池，资讯影响 Agent 会持续收集重大资讯，{target_date} 开盘前形成最终观察池。",
            "news_enriched_count": enriched_count,
        }

    if today < target_day:
        label = "资讯增强中" if enriched_count == 0 else "资讯已增强"
        phase = "enriching" if enriched_count == 0 else "preopen_final"
        message = (
            f"基础观察池已基于 {data_date} 收盘数据生成，资讯影响 Agent 正在为 {target_date} 开盘前做二次筛选。"
            if enriched_count == 0 else
            f"观察池已结合资讯影响 Agent 完成增强，用于 {target_date} 观察。"
        )
        return {
            "pool_phase": phase,
            "pool_phase_label": label,
            "pool_phase_message": message,
            "news_enriched_count": enriched_count,
        }

    if today == target_day:
        if enriched_count > 0:
            return {
                "pool_phase": "final",
                "pool_phase_label": "今日观察池",
                "pool_phase_message": f"今日观察池基于 {data_date} 收盘数据和隔夜资讯影响生成，用于 {target_date} 交易日观察。",
                "news_enriched_count": enriched_count,
            }
        return {
            "pool_phase": "base_pending_news",
            "pool_phase_label": "基础观察池",
            "pool_phase_message": f"当前为基于 {data_date} 收盘数据生成的基础观察池，资讯影响增强尚未完成。",
            "news_enriched_count": enriched_count,
        }

    return {
        "pool_phase": "base",
        "pool_phase_label": "基础观察池",
        "pool_phase_message": f"基于 {data_date} 收盘数据生成，用于下一交易日观察。",
        "news_enriched_count": enriched_count,
    }


def _symbol_aliases(symbol: str) -> list[str]:
    raw = str(symbol or "").strip().upper()
    code = clean_symbol(raw)
    aliases = [raw, code]
    if code and "." not in raw:
        aliases.extend([f"{code}.SH", f"{code}.SZ", f"{code}.BJ"])
    return list(dict.fromkeys(item for item in aliases if item))


def _append_theme_validation_evidence(evidence_chain: list[dict], theme_validation: dict, strategy: dict) -> list[dict]:
    """Mirror the observation-pool theme evidence item for a single-stock debate view."""
    if not evidence_chain or theme_validation.get("status") != "ok":
        return evidence_chain
    verified = (theme_validation.get("verification") or {}).get("level") == "verified"
    evidence_chain.append(
        {
            "factor": "theme_validation",
            "dimension": "industry_theme",
            "label": "主题真实性验证",
            "value": {
                "themes": (theme_validation.get("theme_heat") or {}).get("themes") or [],
                "verification": (theme_validation.get("verification") or {}).get("level"),
                "concept_risk": (theme_validation.get("concept_risk") or {}).get("level"),
            },
            "threshold": "verified business evidence preferred; concept risk should not be high",
            "source": "industry_events+announcements+financial",
            "freshness": "mixed",
            "confidence": "medium" if verified else "low",
            "impact": 4 if verified else -2,
            "direction": "positive" if verified else "negative",
            "explanation": "主题线索已尝试用公告/财务/业务关键词验证；未验证时仅作为行业线索。",
            "strategy_id": strategy.get("id"),
        }
    )
    return evidence_chain


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


@router.get("/{symbol}/observation-summary")
async def get_observation_summary(symbol: str):
    """查询个股最近一次观察池摘要（用于详情页 AI 解读卡片）"""
    from backend.shared.database import SessionLocal
    from backend.shared.models import ResearchObservation
    from sqlalchemy import desc
    db = SessionLocal()
    try:
        row = db.query(ResearchObservation).filter(
            ResearchObservation.symbol.in_(_symbol_aliases(symbol)),
            ResearchObservation.summary_text.isnot(None),
        ).order_by(desc(ResearchObservation.snapshot_date)).first()
        if not row:
            return {"symbol": symbol, "summary_text": None, "snapshot_date": None}
        return {
            "symbol": symbol,
            "summary_text": row.summary_text,
            "score": row.score,
            "snapshot_date": row.snapshot_date.strftime("%Y-%m-%d") if row.snapshot_date else None,
        }
    finally:
        db.close()


@router.get("/{symbol}/debate")
async def get_stock_debate(
    symbol: str,
    request: Request = None,
    strategy: str = Query("auto", description="策略: auto/retail_small/value_quality/growth_momentum/reversal_watch/event_driven/dividend_defensive"),
    include_evidence: bool = Query(True, description="是否返回证据链"),
):
    """单股研究辩论视图：复用观察池证据链、风险裁决和多空反驳逻辑。"""
    strategy = str(_query_default(strategy, "auto")).strip().lower()
    include_evidence = bool(_query_default(include_evidence, True))
    if strategy not in list_strategy_ids(include_auto=True) and strategy != "quality":
        raise HTTPException(status_code=400, detail="strategy 不受支持")

    if request is not None:
        ip = client_ip(request)
        normalized_symbol = symbol.strip().upper()
        await enforce_rate_limit(scope="score:debate:ip", identity=ip, limit=60, window_seconds=60, fail_closed=False)
        await enforce_rate_limit(
            scope="score:debate:ip_symbol",
            identity=f"{ip}:{normalized_symbol}",
            limit=10,
            window_seconds=60,
            fail_closed=False,
        )

    market_regime = await detect_market_regime()
    strategy_payload = resolve_strategy(strategy, market_regime)
    engine_strategy = strategy_payload.get("engine_strategy") or "retail_small"
    stock_data = await get_stock_data(symbol, include_news=True, include_profile=False)
    stock_data = context_builder.enrich(stock_data, models_count=1, quota_ready=True, quota_message="")
    stock_data.setdefault("symbol", symbol)

    risk_lights = build_risk_lights(stock_data)
    score, reasons, risk_flags = _score_daily_candidate(stock_data, risk_lights, engine_strategy)
    score_breakdown = _build_score_breakdown(stock_data, risk_lights, engine_strategy)
    data_grade = (stock_data.get("readiness") or {}).get("data_grade") or {}
    veto_result = evaluate_risk_veto(stock_data, risk_lights, strategy_payload)
    theme_validation = build_theme_validation(stock_data, strategy_payload)
    evidence_chain = build_evidence_chain(
        stock_data,
        risk_lights,
        strategy_payload,
        score_breakdown=score_breakdown,
    )
    evidence_chain = _append_theme_validation_evidence(evidence_chain, theme_validation, strategy_payload)
    debate_view = build_debate_view(stock_data, evidence_chain, veto_result, strategy_payload)
    scored_item = apply_strategy_weighted_score(
        {
            "score": score,
            "score_breakdown": score_breakdown,
        },
        strategy_payload,
    )

    return {
        "symbol": symbol,
        "normalized_symbol": clean_symbol(symbol),
        "name": stock_data.get("name") or symbol,
        "sector": stock_data.get("sector") or "",
        "price": stock_data.get("price"),
        "change_pct": stock_data.get("change_pct"),
        "score": scored_item.get("score", score),
        "base_score": scored_item.get("base_score", score),
        "strategy_score": scored_item.get("strategy_score", score),
        "strategy_score_delta": scored_item.get("strategy_score_delta", 0),
        "strategy_score_blending": scored_item.get("strategy_score_blending"),
        "strategy_weighted_factors": scored_item.get("strategy_weighted_factors") or [],
        "rating": _daily_rating(int(scored_item.get("score", score) or score)),
        "reasons": reasons[:4],
        "risk_flags": risk_flags[:6],
        "risk_lights": risk_lights,
        "veto_result": veto_result,
        "score_breakdown": score_breakdown,
        "evidence_chain": evidence_chain if include_evidence else [],
        "bull_case": debate_view.get("bull_case") or [],
        "bear_case": debate_view.get("bear_case") or [],
        "key_disagreement": debate_view.get("key_disagreement") or [],
        "falsification": debate_view.get("falsification") or [],
        "theme_validation": theme_validation,
        "data_grade": data_grade,
        "market_regime": market_regime,
        "active_strategy": {
            "id": strategy_payload.get("id"),
            "name": strategy_payload.get("name"),
            "selection_mode": strategy_payload.get("selection_mode"),
            "selection_reason": strategy_payload.get("selection_reason"),
            "engine_strategy": engine_strategy,
        },
        "method": {
            "name": "single_stock_debate_v1",
            "description": "基于现有规则评分、证据链和风险裁决生成个股多空研究视图，不构成买卖建议。",
        },
        "disclaimer": "研究辩论仅用于梳理看多、看空和证伪条件，不是买卖建议。",
        "updated_at": datetime.now().isoformat(),
    }


def _extract_capital_flow_item(score_breakdown: list[dict]) -> dict:
    for item in score_breakdown:
        if isinstance(item, dict) and item.get("key") == "capital_flow":
            return item
    return {}


def _extract_capital_flow_features(score_breakdown: list[dict]) -> dict | None:
    item = _extract_capital_flow_item(score_breakdown)
    features = item.get("features") if item else None
    return features if isinstance(features, dict) else None


def _extract_capital_flow_status(score_breakdown: list[dict]) -> str | None:
    item = _extract_capital_flow_item(score_breakdown)
    if not item:
        return None
    features = item.get("features") if isinstance(item.get("features"), dict) else {}
    return item.get("status") or features.get("signal")


async def run_research_pipeline(**kwargs):
    return await _engine_run_research_pipeline(
        **kwargs,
        load_candidates=_load_recommendation_candidates,
        fallback_candidates=_fallback_recommendation_candidates,
        evaluate_candidates=_evaluate_candidates_parallel,
    )


@router.get("/batch/recommend")
async def get_recommendations(
    request: Request = None,
    market: str = Query("ALL", description="市场: ALL/SH/SZ"),
    limit: int = Query(10, ge=5, le=50, description="观察池数量"),
    max_candidates: int = Query(200, ge=20, le=5000, description="候选池扫描数量"),
    force_refresh: bool = Query(False, description="强制重新运行 pipeline（管理员）"),
    strategy: str = Query("auto", description="策略: auto/retail_small/value_quality/growth_momentum/reversal_watch/event_driven/dividend_defensive"),
    include_evidence: bool = Query(True, description="是否返回证据链"),
    include_debate: bool = Query(True, description="是否返回多空辩论"),
    concurrency: int = Query(16, ge=1, le=64, description="候选评分并发数"),
    initial_full_scan: bool = Query(False, description="是否执行一次性全量初始扫描"),
):
    """
    获取每日A股观察池（量价异动驱动，读取预计算结果，秒级响应）
    """
    market = str(_query_default(market, "ALL")).upper()
    limit = int(_query_default(limit, 10))
    max_candidates = int(_query_default(max_candidates, 200))
    force_refresh = bool(_query_default(force_refresh, False))
    requested_strategy = str(_query_default(strategy, "auto")).strip().lower()
    include_evidence = bool(_query_default(include_evidence, True))
    include_debate = bool(_query_default(include_debate, True))
    concurrency = int(_query_default(concurrency, 16))
    initial_full_scan = bool(_query_default(initial_full_scan, False))

    public_force_refresh_allowed = _bool_env("ALLOW_PUBLIC_RECOMMEND_FORCE_REFRESH", False)
    if request is not None and force_refresh and not public_force_refresh_allowed:
        force_refresh = False

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

    if market not in ("ALL", "SH", "SZ"):
        raise HTTPException(status_code=400, detail="market 仅支持 ALL/SH/SZ")

    initial_full_scan_status = "not_requested"
    run_initial_full_scan = False
    if initial_full_scan:
        from backend.shared.cache import get_cache_manager

        cache = await get_cache_manager()
        full_scan_key = f"initial-full-scan:{market}:{requested_strategy}"
        already_completed = await cache.get("daily_recommendations", full_scan_key)
        if already_completed:
            initial_full_scan_status = "already_completed"
        else:
            run_initial_full_scan = _bool_env("DAILY_RECOMMENDATIONS_INITIAL_FULL_SCAN", True)
            initial_full_scan_status = "used" if run_initial_full_scan else "disabled"
            if run_initial_full_scan:
                await cache.set("daily_recommendations", full_scan_key, value=True)
                max_candidates = _int_env("DAILY_RECOMMENDATIONS_INITIAL_FULL_SCAN_MAX", max_candidates, minimum=max_candidates, maximum=10000)

    cache_key = (
        f"{RECOMMENDATION_CACHE_VERSION}:market-{market}:limit-{limit}:max-{max_candidates}:strategy-{requested_strategy}:"
        f"evidence-{int(include_evidence)}:debate-{int(include_debate)}:full-{int(run_initial_full_scan)}"
    )
    from backend.shared.cache import get_cache_manager

    cache = await get_cache_manager()
    if not force_refresh:
        cached = await cache.get("daily_recommendations", cache_key)
        if cached is not None:
            return await _ensure_observation_pool_optimizer(cached)

    if force_refresh:
        result = await run_research_pipeline(
            market=market,
            limit=limit,
            requested_strategy=requested_strategy,
            candidate_limit=max_candidates,
            concurrency=concurrency,
            run_initial_full_scan=run_initial_full_scan,
            include_evidence=include_evidence,
            include_debate=include_debate,
        )
        result["initial_full_scan"] = {
            "requested": initial_full_scan,
            "used": run_initial_full_scan,
            "status": initial_full_scan_status,
        }
        result = await _ensure_observation_pool_optimizer(result)
        await cache.set("daily_recommendations", cache_key, value=result)
        return result

    from backend.shared.database import SessionLocal
    from backend.shared.models import DailySnapshot, PipelineExecution, ResearchObservation

    db = SessionLocal()
    try:
        today_str = date.today().isoformat()
        today_dt = datetime.combine(date.today(), datetime.min.time())

        from backend.services.analysis_service.engine.strategy_config import _ALIASES

        db_strategy: str | None = requested_strategy.strip().lower() if requested_strategy else None
        if db_strategy:
            db_strategy = _ALIASES.get(db_strategy, db_strategy)
        if not db_strategy or db_strategy == "auto":
            # Resolve from latest successful pipeline execution for today
            try:
                latest_exec = db.query(PipelineExecution).filter(
                    PipelineExecution.execution_date == today_str,
                    PipelineExecution.status.in_(["completed", "partial"]),
                    PipelineExecution.strategy_id.isnot(None),
                ).order_by(PipelineExecution.started_at.desc()).first()
                db_strategy = latest_exec.strategy_id if latest_exec and latest_exec.strategy_id else None
            except Exception:
                db.rollback()
                db_strategy = None

        query = db.query(ResearchObservation).filter(
            ResearchObservation.snapshot_date == today_dt,
        )
        if db_strategy:
            query = query.filter(ResearchObservation.strategy_id == db_strategy)
        if market != "ALL":
            query = query.filter(ResearchObservation.symbol.like(f"%.{market}"))

        query = _prefer_formal_pool(query, ResearchObservation)
        query = query.order_by(ResearchObservation.score.desc()).limit(limit * 5)
        rows = query.all()
        rows = sorted(
            rows,
            key=lambda row: (
                _tier_rank_from_factor_snapshot(row.factor_snapshot_json),
                -_priority_from_factor_snapshot(row.factor_snapshot_json),
                -float(row.score or 0),
            ),
        )
        rows = _rebalance_rows_by_observation_bucket(rows, limit)

        pipeline_status = "ok"
        if not rows:
            # Check if today's pipeline ran with 0 output (completed/partial/no_data) —
            # if so, "empty" is intentional and we should NOT fall back to an older pool.
            today_ran_empty = False
            try:
                exec_query = db.query(PipelineExecution).filter(
                    PipelineExecution.execution_date == today_str,
                    PipelineExecution.status.in_(["completed", "partial", "no_data"]),
                )
                if db_strategy:
                    exec_query = exec_query.filter(PipelineExecution.strategy_id == db_strategy)
                today_exec = exec_query.order_by(PipelineExecution.started_at.desc()).first()
                today_ran_empty = today_exec is not None and (today_exec.total_output or 0) == 0
            except Exception:
                db.rollback()

            if today_ran_empty:
                pipeline_status = "empty"
            else:
                latest_query = db.query(ResearchObservation.snapshot_date)
                if market != "ALL":
                    latest_query = latest_query.filter(ResearchObservation.symbol.like(f"%.{market}"))
                if db_strategy:
                    latest_query = latest_query.filter(ResearchObservation.strategy_id == db_strategy)
                latest_snapshot_date = latest_query.order_by(ResearchObservation.snapshot_date.desc()).limit(1).scalar()
                if latest_snapshot_date is not None:
                    query = db.query(ResearchObservation).filter(
                        ResearchObservation.snapshot_date == latest_snapshot_date,
                    )
                    if db_strategy:
                        query = query.filter(ResearchObservation.strategy_id == db_strategy)
                    if market != "ALL":
                        query = query.filter(ResearchObservation.symbol.like(f"%.{market}"))
                    query = _prefer_formal_pool(query, ResearchObservation)
                    query = query.order_by(ResearchObservation.score.desc()).limit(limit * 5)
                    rows = query.all()
                    rows = sorted(
                        rows,
                        key=lambda row: (
                            _tier_rank_from_factor_snapshot(row.factor_snapshot_json),
                            -_priority_from_factor_snapshot(row.factor_snapshot_json),
                            -float(row.score or 0),
                        ),
                    )
                    rows = _rebalance_rows_by_observation_bucket(rows, limit)
                pipeline_status = "stale" if rows else "empty"

        symbols = [row.symbol for row in rows]
        name_map: dict[str, str] = {}
        change_map: dict[str, float] = {}
        if symbols:
            snapshot_date_str = rows[0].snapshot_date.strftime("%Y-%m-%d") if rows[0].snapshot_date else today_str
            snap_rows = db.query(DailySnapshot.symbol, DailySnapshot.name, DailySnapshot.change_pct).filter(
                DailySnapshot.symbol.in_(symbols),
                DailySnapshot.trade_date == snapshot_date_str,
            ).all()
            name_map = {r.symbol: r.name or "" for r in snap_rows}
            change_map = {r.symbol: r.change_pct for r in snap_rows if r.change_pct is not None}
            if not name_map:
                from backend.shared.models import Stock
                aliases_by_symbol = {symbol: _symbol_aliases(symbol) for symbol in symbols}
                lookup_values = list({alias for aliases in aliases_by_symbol.values() for alias in aliases})
                stock_rows = db.query(Stock.symbol, Stock.name).filter(Stock.symbol.in_(lookup_values)).all()
                stock_name_by_symbol = {r.symbol: r.name or "" for r in stock_rows}
                name_map = {
                    symbol: next((stock_name_by_symbol[alias] for alias in aliases if stock_name_by_symbol.get(alias)), "")
                    for symbol, aliases in aliases_by_symbol.items()
                }

        data_date = rows[0].snapshot_date.strftime("%Y-%m-%d") if rows and rows[0].snapshot_date else None
        target_date = _observation_target_date(data_date)
        phase_metadata = _pool_phase_metadata(
            data_date=data_date,
            target_date=target_date,
            pipeline_status=pipeline_status,
            rows=rows,
        )
        recommendations = []
        for row in rows:
            debate_json = row.debate_json or {}
            factor_snapshot = row.factor_snapshot_json or {}
            # factor_snapshot 可能是旧的 list 格式（兼容）或新的 dict 格式
            if isinstance(factor_snapshot, list):
                factor_snapshot = {"factors": factor_snapshot}
            rec = {
                "symbol": row.symbol,
                "name": name_map.get(row.symbol, ""),
                "score": row.score,
                "strategy_id": row.strategy_id,
                "candidate_source": "snapshot_fast_recovery" if row.strategy_id == "snapshot_fast_recovery" else "database",
                "price": row.close_price,
                "change_pct": change_map.get(row.symbol),
                "score_breakdown": row.score_breakdown_json or [],
                "capital_flow_features": _extract_capital_flow_features(row.score_breakdown_json or []),
                "capital_flow_status": _extract_capital_flow_status(row.score_breakdown_json or []),
                "evidence_chain": row.evidence_chain_json or [] if include_evidence else [],
                "_news_impact_items": _news_impact_items(row),
                "veto_result": row.veto_result_json or {},
                "bull_case": debate_json.get("bull_case", []) if include_debate else [],
                "bear_case": debate_json.get("bear_case", []) if include_debate else [],
                "key_disagreement": debate_json.get("key_disagreement", []) if include_debate else [],
                "falsification": debate_json.get("falsification", []) if include_debate else [],
                "regime": row.regime,
                "snapshot_date": row.snapshot_date.strftime("%Y-%m-%d") if row.snapshot_date else None,
                "summary_text": row.summary_text or None,
                # 新增分层/动作字段
                "tier": factor_snapshot.get("tier"),
                "tier_reason": factor_snapshot.get("tier_reason"),
                "priority_score": factor_snapshot.get("priority_score"),
                "observation_action": factor_snapshot.get("observation_action"),
                "sector": factor_snapshot.get("sector") or factor_snapshot.get("industry_name"),
                "industry_name": factor_snapshot.get("industry_name"),
                "observation_bucket": factor_snapshot.get("observation_bucket"),
                "observation_bucket_label": factor_snapshot.get("observation_bucket_label"),
                "trigger_condition": factor_snapshot.get("trigger_condition"),
                "invalidation_condition": factor_snapshot.get("invalidation_condition"),
                "risk_warning": factor_snapshot.get("risk_warning"),
                "chase_high_penalty": factor_snapshot.get("chase_high_penalty"),
                "news_freshness_score": factor_snapshot.get("news_freshness_score"),
                "diversification_penalty": factor_snapshot.get("diversification_penalty"),
                "review_feedback": factor_snapshot.get("review_feedback"),
                "pool_optimizer": factor_snapshot.get("pool_optimizer"),
                "optimizer_adjustments": factor_snapshot.get("optimizer_adjustments"),
            }
            recommendations.append(rec)

        # pool_summary: 优先从 Redis 读取 scoped key，fallback latest，再 fallback 实时计算
        cached_pool_summary = {}
        try:
            if data_date and db_strategy:
                cached_pool_summary = await cache.get("pool_summary", f"{data_date}:{db_strategy}:{market}") or {}
            if not cached_pool_summary:
                cached_pool_summary = await cache.get("pool_summary", f"latest:{market}") or {}
            if not cached_pool_summary:
                cached_pool_summary = await cache.get("pool_summary", "latest:ALL") or {}
        except Exception:
            pass
        if not cached_pool_summary and recommendations:
            try:
                from backend.services.analysis_service.engine.pool_summary_generator import generate_pool_summary
                cached_pool_summary = generate_pool_summary(recommendations, {})
            except Exception:
                pass

        # Derive active_strategy from actual data, not hardcoded
        actual_strategy_id = db_strategy
        if not actual_strategy_id and rows:
            actual_strategy_id = rows[0].strategy_id
        _active_strategy: dict = {"id": actual_strategy_id or "unknown", "selection_mode": "database_recovery"}
        try:
            if actual_strategy_id:
                from backend.services.analysis_service.engine.strategy_config import load_strategy
                _strat = load_strategy(actual_strategy_id)
                _active_strategy = {
                    "id": _strat["id"],
                    "name": _strat.get("name", actual_strategy_id),
                    "selection_mode": "database_recovery",
                    "engine_strategy": _strat.get("engine_strategy"),
                }
        except Exception:
            pass

        result = {
            "recommendations": recommendations,
            "count": len(recommendations),
            "market": market,
            "status": "ok",
            "pipeline_status": pipeline_status,
            "candidate_source": "snapshot_fast_recovery" if _is_recovery_pool(rows) else "database",
            "data_date": data_date,
            "pool_summary": cached_pool_summary,
            "target_date": target_date,
            "target_date_note": "next_trading_day" if target_date else "empty",
            **phase_metadata,
            "data_date_note": (
                "latest_trading_day" if pipeline_status == "stale" else
                "current_trading_day" if pipeline_status == "ok" else
                "empty"
            ),
            "method": {
                "name": "anomaly_driven_v1",
                "description": "基于全市场量价异动筛选，定时采集+本地评分，秒级响应。",
            },
            "active_strategy": _active_strategy,
            "updated_at": datetime.now().isoformat(),
            "disclaimer": "每日观察池仅用于筛选值得继续研究的标的，不是买入建议；需结合个人风险承受能力和完整信息独立判断。",
        }
        result = await _ensure_observation_pool_optimizer(result)
        await cache.set("daily_recommendations", cache_key, value=result)
        return result
    finally:
        db.close()


@router.get("/batch/intraday-confirmation")
async def get_intraday_confirmation(
    request: Request = None,
    market: str = Query("ALL", description="市场: ALL/SH/SZ"),
    limit: int = Query(20, ge=5, le=50, description="确认数量"),
    strategy: str = Query("auto", description="策略"),
    concurrency: int = Query(8, ge=1, le=20, description="行情确认并发数"),
):
    """Return realtime confirmation states for the current observation pool."""
    market = str(_query_default(market, "ALL")).upper()
    limit = int(_query_default(limit, 20))
    requested_strategy = str(_query_default(strategy, "auto")).strip().lower()
    concurrency = int(_query_default(concurrency, 8))
    if request is not None:
        ip = client_ip(request)
        await enforce_rate_limit(
            scope="score:intraday-confirmation:ip",
            identity=ip,
            limit=20,
            window_seconds=60,
            fail_closed=False,
        )
    pool = await get_recommendations(
        request=None,
        market=market,
        limit=limit,
        max_candidates=200,
        force_refresh=False,
        strategy=requested_strategy,
        include_evidence=True,
        include_debate=False,
        concurrency=concurrency,
        initial_full_scan=False,
    )
    rows = pool.get("recommendations") or []
    confirmation = await build_intraday_confirmation(rows, concurrency=concurrency)
    return {
        **confirmation,
        "market": market,
        "count": len(rows),
        "data_date": pool.get("data_date"),
        "target_date": pool.get("target_date"),
        "pool_phase": pool.get("pool_phase"),
        "pool_phase_label": pool.get("pool_phase_label"),
    }
