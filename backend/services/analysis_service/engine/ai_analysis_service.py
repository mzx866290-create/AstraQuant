from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.shared.auth import check_quota_available, increment_quota
from backend.shared.cache import get_cache_manager
from backend.shared.models import AIModel, AIUsageLog, User
from backend.shared.schemas import (
    AIBatchSummaryRequest,
    AIFollowUpRequest,
    AIFollowUpResponse,
    AIAnalysisRequest,
    AIAnalysisResponse,
    AIModelPublicResponse,
    UserQuotaResponse,
)
from backend.services.analysis_service.engine.ai_analysis_data import clean_symbol, get_stock_data
from backend.services.analysis_service.engine.ai_analysis_fallbacks import (
    build_batch_brief,
    build_batch_error_item,
    build_change_alerts,
    build_fallback_analysis,
    build_follow_up_fallback,
    build_risk_lights,
    build_source_citation,
)
from backend.services.analysis_service.engine.ai_analysis_support import (
    analysis_cache_key,
    batch_item_cache_key,
    build_guarded_trust_analysis,
    clean_model_analysis,
    prepare_cached_analysis_response,
)
from backend.services.analysis_service.engine.ai_client import ai_client
from backend.services.analysis_service.engine.context_builder import context_builder
from backend.services.analysis_service.engine.data_quality import build_readiness
from backend.services.analysis_service.engine.model_router import model_health_checker, model_router
from backend.services.analysis_service.engine.prompt_builder import PromptBuilder
from backend.services.analysis_service.engine.report_guard import ReportGuard

logger = logging.getLogger(__name__)


async def _cache_get(key: str, category: str = "ai_analysis_report", mark_hit: bool = True) -> dict | None:
    cache = await get_cache_manager()
    cached = await cache.get(category, key)
    return prepare_cached_analysis_response(cached, mark_hit=mark_hit)


async def _cache_set(key: str, value: dict, category: str = "ai_analysis_report") -> None:
    cache = await get_cache_manager()
    await cache.set(category, key, value=value)


async def list_available_models(current_user: User, db: Session) -> list[AIModelPublicResponse]:
    user_role = current_user.role or "free"
    models = (
        db.query(AIModel)
        .filter(AIModel.is_active == True)
        .order_by(AIModel.sort_order, AIModel.id)
        .all()
    )

    available = []
    for model in models:
        allowed_roles = model.allowed_roles.split(",") if model.allowed_roles else ["free", "premium", "admin"]
        if user_role not in allowed_roles:
            continue
        health = await model_health_checker.get_cached(model.id)
        available.append(
            AIModelPublicResponse(
                id=model.id,
                name=model.name,
                provider=model.provider,
                description=model.description,
                health_status=health.get("status"),
                health_latency_ms=health.get("latency_ms"),
                health_checked_at=health.get("checked_at"),
            )
        )
    return available


async def get_model_health(refresh: bool, analysis_grade: bool, current_user: User, db: Session) -> dict:
    from backend.services.analysis_service.engine.model_health_scheduler import model_health_scheduler

    models = (
        db.query(AIModel)
        .filter(AIModel.is_active == True)
        .order_by(AIModel.sort_order, AIModel.id)
        .all()
    )
    result = []
    for model in models:
        if not model_router.allowed(model, current_user):
            continue
        health = (
            await model_health_checker.probe(model, ai_client, analysis_grade=analysis_grade)
            if refresh
            else await model_health_checker.get_cached(model.id)
        )
        result.append(
            {
                "id": model.id,
                "name": model.name,
                "provider": model.provider,
                **health,
                "model_id": model.model_id,
            }
        )
    return {
        "scheduler": {
            "enabled": model_health_scheduler.enabled(),
            "interval_seconds": model_health_scheduler.interval_seconds(),
        },
        "models": result,
    }


async def get_quota(current_user: User, db: Session) -> UserQuotaResponse:
    from backend.shared.auth import get_user_quota

    quota = get_user_quota(current_user.id)
    now = datetime.now(timezone.utc)
    if quota.last_reset_daily and quota.last_reset_daily.replace(tzinfo=timezone.utc) < now.replace(hour=0, minute=0, second=0, microsecond=0):
        quota.daily_used = 0
        quota.last_reset_daily = now
        db.commit()
    if quota.last_reset_monthly and quota.last_reset_monthly.replace(tzinfo=timezone.utc) < now.replace(day=1, hour=0, minute=0, second=0, microsecond=0):
        quota.monthly_used = 0
        quota.last_reset_monthly = now
        db.commit()

    return UserQuotaResponse(
        user_id=current_user.id,
        daily_limit=quota.daily_limit,
        monthly_limit=quota.monthly_limit,
        daily_used=quota.daily_used,
        monthly_used=quota.monthly_used,
        daily_remaining=max(0, quota.daily_limit - quota.daily_used),
        monthly_remaining=max(0, quota.monthly_limit - quota.monthly_used),
    )


async def get_analysis_readiness(symbol: str, current_user: User, db: Session) -> dict:
    stock_data = await get_stock_data(symbol, include_news=True)
    models_count = db.query(AIModel).filter(AIModel.is_active == True).count()
    can_use, quota_msg = check_quota_available(current_user.id)
    readiness = build_readiness(stock_data, models_count, can_use, quota_msg)
    readiness.update({"symbol": clean_symbol(symbol), "crawl_status": _get_crawl_status(clean_symbol(symbol), db)})
    return readiness


def _record_ai_usage(
    db: Session,
    *,
    current_user: User,
    model: AIModel,
    symbol: str,
    prompt_tokens: int,
    completion_tokens: int,
    tokens_used: int,
    cost: float,
    status: str,
    error_message: str | None,
    response_time_ms: int,
) -> AIUsageLog:
    log = AIUsageLog(
        user_id=current_user.id,
        model_id=model.id,
        stock_symbol=symbol,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=tokens_used,
        cost=cost,
        status=status,
        error_message=error_message,
        response_time_ms=response_time_ms,
    )
    db.add(log)
    if status == "success":
        increment_quota(current_user.id)
    db.commit()
    return log


async def analyze_stock(request: AIAnalysisRequest, current_user: User, db: Session) -> AIAnalysisResponse:
    can_use, error_msg = check_quota_available(current_user.id)
    if not can_use:
        raise HTTPException(status_code=403, detail=error_msg)

    requested_model = db.query(AIModel).filter(AIModel.id == request.model_id).first()
    if not requested_model or not requested_model.is_active:
        raise HTTPException(status_code=404, detail="模型不存在或已禁用")
    if not model_router.allowed(requested_model, current_user):
        raise HTTPException(status_code=403, detail="无权使用该模型")

    report_template = PromptBuilder.normalize_report_template(request.report_template)
    report_mode = PromptBuilder.normalize_report_mode(request.report_mode)
    audience = PromptBuilder.normalize_audience(request.audience)
    prompt_style = PromptBuilder.normalize_prompt_style(request.prompt_style, audience)
    key = analysis_cache_key(current_user.id, request, report_mode, audience, report_template, prompt_style)
    cached = None if request.force_refresh else await _cache_get(key)
    if cached:
        return AIAnalysisResponse(**cached)

    stock_data = await get_stock_data(request.symbol, include_news=request.include_news)
    stock_data = context_builder.enrich(
        stock_data,
        db.query(AIModel).filter(AIModel.is_active == True).count(),
        True,
        "",
    )

    system_prompt = PromptBuilder.system_prompt(report_mode, audience, report_template, prompt_style)
    user_prompt = PromptBuilder.analysis_prompt(
        request.symbol,
        stock_data,
        request.question,
        request.framework,
        report_mode,
        audience,
        report_template,
        prompt_style,
    )
    config = PromptBuilder.model_config(report_mode, report_template)
    was_trimmed = False
    was_sanitized = False

    try:
        result, actual_model, fallback_reason = await model_router.analyze_with_fallback(
            db=db,
            requested_model=requested_model,
            user=current_user,
            ai_client=ai_client,
            config=config,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        content, was_sanitized = clean_model_analysis(result.get("content", ""))
        analysis = content + "\n" + build_source_citation(request.symbol, stock_data)
        analysis, was_trimmed = ReportGuard.enforce_length(analysis, report_mode, report_template)
        status = "success"
        error_message = None
        tokens_used = result["total_tokens"]
        response_time_ms = result["response_time_ms"]
        prompt_tokens = result.get("prompt_tokens", 0)
        completion_tokens = result.get("completion_tokens", 0)
        cost = result.get("cost", 0.0)
    except Exception as exc:
        logger.warning("AI model call failed, using local fallback: %s", exc)
        actual_model = requested_model
        fallback_reason = f"AI模型失败，当前为本地规则摘要: {exc}"
        analysis = build_fallback_analysis(request.symbol, stock_data, str(exc), audience=audience)
        status = "error"
        error_message = str(exc)
        tokens_used = 0
        response_time_ms = 0
        prompt_tokens = 0
        completion_tokens = 0
        cost = 0.0

    risk_lights = build_risk_lights(stock_data)
    analysis, final_sanitized = ReportGuard.sanitize_advice_language(analysis)
    was_sanitized = was_sanitized or final_sanitized
    analysis, trust_boundary = build_guarded_trust_analysis(
        analysis,
        stock_data,
        risk_lights,
        status=status,
        fallback_reason=fallback_reason,
        sanitized=was_sanitized,
        trimmed=was_trimmed,
    )

    _record_ai_usage(
        db,
        current_user=current_user,
        model=actual_model,
        symbol=request.symbol,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tokens_used=tokens_used,
        cost=cost,
        status=status,
        error_message=error_message,
        response_time_ms=response_time_ms,
    )

    response = {
        "symbol": request.symbol,
        "model_name": actual_model.name if status == "success" else f"{requested_model.name}（本地兜底）",
        "analysis": analysis,
        "tokens_used": tokens_used,
        "response_time_ms": response_time_ms,
        "created_at": datetime.now(timezone.utc),
        "requested_model": requested_model.name,
        "actual_model": actual_model.name if status == "success" else "local-fallback",
        "fallback_reason": fallback_reason,
        "data_quality": stock_data.get("data_quality"),
        "readiness": stock_data.get("readiness"),
        "risk_lights": risk_lights,
        "trust_boundary": trust_boundary,
        "report_meta": {
            "report_template": report_template,
            "prompt_style": prompt_style,
            "report_mode": report_mode,
            "audience": audience,
            "trimmed": was_trimmed,
            "sanitized": was_sanitized,
            "length": len(analysis),
            "force_refresh": request.force_refresh,
            "status": status,
            "data_grade": (stock_data.get("readiness") or {}).get("data_grade"),
        },
        "cache_hit": False,
    }
    if status == "success":
        cached_response = dict(response)
        if isinstance(cached_response.get("report_meta"), dict):
            cached_response["report_meta"] = dict(cached_response["report_meta"])
            cached_response["report_meta"]["force_refresh"] = False
        await _cache_set(key, cached_response)
    return AIAnalysisResponse(**response)


async def follow_up_analysis(request: AIFollowUpRequest, current_user: User, db: Session) -> AIFollowUpResponse:
    can_use, error_msg = check_quota_available(current_user.id)
    if not can_use:
        raise HTTPException(status_code=403, detail=error_msg)

    requested_model = db.query(AIModel).filter(AIModel.id == request.model_id).first()
    if not requested_model or not requested_model.is_active:
        raise HTTPException(status_code=404, detail="模型不存在或已禁用")
    if not model_router.allowed(requested_model, current_user):
        raise HTTPException(status_code=403, detail="无权使用该模型")

    audience = PromptBuilder.normalize_audience(request.audience)
    prompt_style = PromptBuilder.normalize_prompt_style(request.prompt_style, audience)
    system_prompt = PromptBuilder.follow_up_system_prompt(audience, prompt_style)
    user_prompt = PromptBuilder.follow_up_prompt(
        request.symbol,
        request.analysis,
        request.question,
        request.report_meta,
    )
    config = PromptBuilder.follow_up_config()
    answer_sanitized = False

    try:
        result, actual_model, fallback_reason = await model_router.analyze_with_fallback(
            db=db,
            requested_model=requested_model,
            user=current_user,
            ai_client=ai_client,
            config=config,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        answer = (result.get("content") or "").strip()
        if len(answer) < 8:
            raise RuntimeError("AI model returned an empty or too-short answer")
        status = "success"
        error_message = None
        tokens_used = result.get("total_tokens", 0)
        response_time_ms = result.get("response_time_ms", 0)
        prompt_tokens = result.get("prompt_tokens", 0)
        completion_tokens = result.get("completion_tokens", 0)
        cost = result.get("cost", 0.0)
    except Exception as exc:
        logger.warning("AI follow-up failed, using local fallback: %s", exc)
        actual_model = requested_model
        fallback_reason = f"AI追问失败，当前为本地解惑提示: {exc}"
        answer = build_follow_up_fallback(request.question, str(exc))
        status = "error"
        error_message = str(exc)
        tokens_used = 0
        response_time_ms = 0
        prompt_tokens = 0
        completion_tokens = 0
        cost = 0.0

    answer, answer_sanitized = ReportGuard.sanitize_advice_language(answer)
    if "不构成投资建议" not in answer:
        answer = answer.rstrip() + "\n\n以上解读仅供学习和参考，不构成投资建议。"

    _record_ai_usage(
        db,
        current_user=current_user,
        model=actual_model,
        symbol=request.symbol,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tokens_used=tokens_used,
        cost=cost,
        status=status,
        error_message=error_message,
        response_time_ms=response_time_ms,
    )

    return AIFollowUpResponse(
        symbol=request.symbol,
        model_name=actual_model.name if status == "success" else f"{requested_model.name}（本地兜底）",
        answer=answer,
        tokens_used=tokens_used,
        response_time_ms=response_time_ms,
        created_at=datetime.now(timezone.utc),
        requested_model=requested_model.name,
        actual_model=actual_model.name if status == "success" else "local-fallback",
        fallback_reason=fallback_reason,
        report_meta={
            "prompt_style": prompt_style,
            "audience": audience,
            "status": status,
            "sanitized": answer_sanitized,
        },
    )


async def batch_summary(request: AIBatchSummaryRequest, current_user: User, db: Session) -> dict:
    report_mode = PromptBuilder.normalize_report_mode(request.report_mode)
    audience = PromptBuilder.normalize_audience(request.audience)
    symbols = list(dict.fromkeys(request.symbols[:30]))
    models_count = db.query(AIModel).filter(AIModel.is_active == True).count()
    semaphore = asyncio.Semaphore(5)

    async def build_one(symbol: str) -> dict:
        cache_key = batch_item_cache_key(symbol, report_mode, audience, request.include_news)
        cached = None if request.force_refresh else await _cache_get(cache_key, category="ai_batch_summary", mark_hit=False)
        if cached:
            cached["batch_cache_hit"] = True
            cached["force_refresh"] = False
            return cached
        try:
            async with semaphore:
                stock_data = await get_stock_data(symbol, include_news=request.include_news)
            stock_data = context_builder.enrich(stock_data, models_count, True, "")
            data_quality = stock_data.get("data_quality")
            readiness = stock_data.get("readiness")
            item = {
                "symbol": symbol,
                "name": stock_data.get("name", symbol),
                "price": stock_data.get("price"),
                "change_pct": stock_data.get("change_pct"),
                "summary": build_batch_brief(symbol, stock_data, audience),
                "risk_lights": build_risk_lights(stock_data),
                "change_alerts": build_change_alerts(stock_data),
                "data_quality": data_quality,
                "readiness": readiness,
                "report_mode": report_mode,
                "audience": audience,
                "model_status": "local-summary",
                "batch_cache_hit": False,
                "force_refresh": request.force_refresh,
            }
            cached_item = dict(item)
            cached_item["force_refresh"] = False
            await _cache_set(cache_key, cached_item, category="ai_batch_summary")
            return item
        except Exception as exc:
            item = build_batch_error_item(symbol, report_mode, audience, str(exc))
            item["force_refresh"] = request.force_refresh
            return item

    rows = await asyncio.gather(*(build_one(symbol) for symbol in symbols))
    return {"count": len(rows), "items": rows}


def _get_crawl_status(code: str, db: Session) -> dict:
    try:
        from backend.shared.models import CrawlStatus

        rows = db.query(CrawlStatus).filter(CrawlStatus.stock_symbol == code).all()
        return {
            row.data_type: {
                "status": row.status,
                "source": row.source,
                "fetched": row.fetched_count,
                "saved": row.saved_count,
                "error_message": row.error_message,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in rows
        }
    except Exception:
        return {}
