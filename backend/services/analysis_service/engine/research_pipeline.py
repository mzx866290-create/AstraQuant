from __future__ import annotations

from datetime import date, datetime
from typing import Any

from backend.services.analysis_service.engine.market_regime import detect_market_regime
from backend.services.analysis_service.engine.evidence_chain import build_evidence_chain
from backend.services.analysis_service.engine.recommendation_engine import (
    _PRODUCTION_SMALL_CANDIDATE_POOL_WARNING,
    _empty_recommendations_result,
    _evaluate_candidates_parallel,
    _fallback_recommendation_candidates,
    _load_recommendation_candidates,
    _mark_fallback_recommendation,
    _mark_fallback_recommendations,
    _supplement_development_candidates,
)
from backend.services.analysis_service.engine.debate_engine import build_debate_view
from backend.services.analysis_service.engine.risk_veto import evaluate_risk_veto
from backend.services.analysis_service.engine.review_tracker import save_observation_snapshots
from backend.services.analysis_service.engine.strategy_config import resolve_strategy
from backend.services.analysis_service.engine.strategy_filters import (
    append_strategy_filter_warnings,
    evaluate_strategy_filters,
)
from backend.services.analysis_service.engine.strategy_scoring import apply_strategy_weighted_score
from backend.services.analysis_service.engine.theme_validation import build_theme_validation
from backend.shared.config import is_production


def _strategy_label(strategy_id: str) -> str:
    mapping = {
        "retail_small": "散户小而美",
        "value_quality": "价值质量",
        "growth_momentum": "成长动量",
        "reversal_watch": "反转观察",
        "event_driven": "事件驱动",
        "dividend_defensive": "红利防御",
    }
    return mapping.get(strategy_id, strategy_id)


def _selection_meta(candidates: list[dict]) -> tuple[int, str, str]:
    universe_count = max((int(row.get("_candidate_universe_count") or 0) for row in candidates), default=0)
    rotation_date = next(
        (str(row.get("_candidate_rotation_date")) for row in candidates if row.get("_candidate_rotation_date")),
        date.today().isoformat(),
    )
    selection = next(
        (str(row.get("_candidate_selection")) for row in candidates if row.get("_candidate_selection")),
        "daily_rotating_db_sample" if candidates else "none",
    )
    return universe_count, rotation_date, selection


def _apply_phase1_annotations(
    item: dict,
    strategy: dict,
    market_regime: dict,
    *,
    include_evidence: bool,
    include_debate: bool,
) -> dict | None:
    marked = dict(item)
    stock_data = dict(item.get("stock_data") or {})
    stock_data.setdefault("symbol", item.get("symbol"))
    stock_data.setdefault("name", item.get("name"))
    stock_data.setdefault("readiness", {"data_grade": dict(item.get("data_grade") or {})})
    if "price" not in stock_data and "price" in item and item.get("price") is not None:
        stock_data["price"] = item.get("price")
    stock_data.setdefault("quote", {})
    stock_data.setdefault("financial", {})
    stock_data.setdefault("news_sentiment", {})
    stock_data.setdefault("industry_event_context", {})
    if "data_quality" not in stock_data:
        stock_data["data_quality"] = {}
    risk_lights = dict(item.get("risk_lights") or {})
    veto_result = evaluate_risk_veto(stock_data, risk_lights, strategy)
    if not veto_result["passed"]:
        return None

    evidence_chain = (
        build_evidence_chain(
            stock_data,
            risk_lights,
            strategy,
            score_breakdown=list(item.get("score_breakdown") or []),
        )
        if include_evidence or include_debate
        else []
    )
    theme_validation = build_theme_validation(stock_data, strategy)
    if evidence_chain and theme_validation.get("status") == "ok":
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
                "confidence": "medium" if (theme_validation.get("verification") or {}).get("level") == "verified" else "low",
                "impact": 4 if (theme_validation.get("verification") or {}).get("level") == "verified" else -2,
                "direction": "positive" if (theme_validation.get("verification") or {}).get("level") == "verified" else "negative",
                "explanation": "主题线索已尝试用公告/财务/业务关键词验证；未验证时仅作为行业线索。",
                "strategy_id": strategy.get("id"),
            }
        )
    debate_view = build_debate_view(stock_data, evidence_chain, veto_result, strategy) if include_debate else {}

    marked["veto_result"] = veto_result
    marked["strategy_id"] = strategy["id"]
    marked["market_regime"] = market_regime.get("regime")
    marked["theme_validation"] = theme_validation
    if include_evidence:
        marked["evidence_chain"] = evidence_chain
    if include_debate:
        marked["bull_case"] = debate_view.get("bull_case") or []
        marked["bear_case"] = debate_view.get("bear_case") or []
        marked["key_disagreement"] = debate_view.get("key_disagreement") or []
        marked["falsification"] = debate_view.get("falsification") or []
    if veto_result.get("warnings"):
        warning_labels = [entry.get("detail") for entry in veto_result["warnings"] if entry.get("detail")]
        marked["risk_flags"] = list(dict.fromkeys([*(marked.get("risk_flags") or []), *warning_labels]))[:6]
    marked.pop("stock_data", None)
    marked = apply_strategy_weighted_score(marked, strategy)
    filter_result = evaluate_strategy_filters(marked, strategy)
    if not filter_result["passed"]:
        return None
    marked["strategy_filter_result"] = filter_result
    return append_strategy_filter_warnings(marked, filter_result)


async def run_research_pipeline(
    *,
    market: str,
    limit: int,
    requested_strategy: str,
    candidate_limit: int,
    concurrency: int,
    run_initial_full_scan: bool,
    include_evidence: bool = True,
    include_debate: bool = True,
    load_candidates=_load_recommendation_candidates,
    fallback_candidates=_fallback_recommendation_candidates,
    supplement_candidates=_supplement_development_candidates,
    evaluate_candidates=_evaluate_candidates_parallel,
    mark_fallback=_mark_fallback_recommendation,
    mark_fallback_batch=_mark_fallback_recommendations,
    empty_result_factory=_empty_recommendations_result,
) -> dict[str, Any]:
    market_regime = await detect_market_regime()
    strategy = resolve_strategy(requested_strategy, market_regime)
    engine_strategy = strategy.get("engine_strategy") or "retail_small"

    candidates = load_candidates(market, candidate_limit)
    if run_initial_full_scan:
        for row in candidates:
            row["_candidate_selection"] = "initial_full_scan"

    candidate_universe_count, candidate_rotation_date, candidate_selection = _selection_meta(candidates)
    candidate_source = "db"
    fallback_codes: set[str] = set()
    warnings: list[str] = []

    if not candidates:
        if is_production():
            result = empty_result_factory(
                market=market,
                strategy=strategy["id"],
                candidate_limit=candidate_limit,
                concurrency=concurrency,
                warnings=["recommendation candidate pool is empty; no recommendations are available"],
            )
            result["market_regime"] = market_regime
            result["active_strategy"] = {
                "id": strategy["id"],
                "name": strategy.get("name"),
                "selection_mode": strategy.get("selection_mode"),
            }
            return result

        candidates, candidate_source, warnings, fallback_codes = supplement_candidates(
            candidates,
            fallback_candidates(market),
            candidate_limit,
        )
        candidate_universe_count, candidate_rotation_date, candidate_selection = _selection_meta(candidates)
    elif is_production() and len(candidates) < limit:
        warnings.append(_PRODUCTION_SMALL_CANDIDATE_POOL_WARNING)
    elif not run_initial_full_scan and not is_production() and len(candidates) < candidate_limit:
        candidates, candidate_source, warnings, fallback_codes = supplement_candidates(
            candidates,
            fallback_candidates(market),
            candidate_limit,
        )
        candidate_universe_count, candidate_rotation_date, candidate_selection = _selection_meta(candidates)

    scored = await evaluate_candidates(candidates, engine_strategy, concurrency=concurrency)
    if candidate_source == "fallback":
        scored = [mark_fallback(item) for item in scored]
    elif candidate_source == "mixed":
        scored = mark_fallback_batch(scored, fallback_codes)

    filtered: list[dict] = []
    for item in scored:
        annotated = _apply_phase1_annotations(
            item,
            strategy,
            market_regime,
            include_evidence=include_evidence,
            include_debate=include_debate,
        )
        if annotated:
            filtered.append(annotated)

    filtered.sort(
        key=lambda x: (
            x.get("strategy_score", x.get("score", 0)),
            x["data_grade"].get("grade") == "A",
            -len(x.get("risk_flags", [])),
        ),
        reverse=True,
    )
    recommendations = filtered[:limit]

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
        "candidate_universe_count": candidate_universe_count,
        "scored_count": len(scored),
        "selection": {
            "mode": candidate_selection,
            "rotation_date": candidate_rotation_date,
            "universe_count": candidate_universe_count,
            "evaluated_count": len(candidates),
        },
        "market_regime": market_regime,
        "active_strategy": {
            "id": strategy["id"],
            "name": strategy.get("name"),
            "selection_mode": strategy.get("selection_mode"),
            "selection_reason": strategy.get("selection_reason"),
            "engine_strategy": engine_strategy,
        },
        "method": {
            "name": "daily_observation_pool_v2",
            "description": "基于市场环境、策略包、风险否决和现有规则评分生成研究观察池，不构成买卖建议。",
            "strategy": strategy["id"],
            "strategy_label": _strategy_label(strategy["id"]),
        },
        "updated_at": datetime.now().isoformat(),
        "phase": "phase1_research_orchestration",
    }
    save_observation_snapshots(date.today(), str(market_regime.get("regime") or "unknown"), recommendations)
    return result
