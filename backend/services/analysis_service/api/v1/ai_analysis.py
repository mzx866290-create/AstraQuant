from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.shared.auth import get_current_user
from backend.shared.database import get_db
from backend.shared.models import User
from backend.shared.schemas import (
    AIBatchSummaryRequest,
    AIFollowUpRequest,
    AIFollowUpResponse,
    AIAnalysisRequest,
    AIAnalysisResponse,
    AIModelPublicResponse,
    UserQuotaResponse,
)
from backend.services.analysis_service.engine import ai_analysis_service
from backend.services.analysis_service.engine.ai_analysis_data import (
    build_indicators as _build_indicators,
    clean_symbol as _clean_symbol,
    fetch_kline as _fetch_kline,
    fetch_public_profile as _fetch_public_profile,
    fetch_public_profile_sync as _fetch_public_profile_sync,
    fetch_quote as _fetch_quote,
    get_stock_data as _get_stock_data,
    map_financial as _map_financial,
    parse_profile_date as _parse_profile_date,
    resolve_change_pct as _resolve_change_pct,
)
from backend.services.analysis_service.engine.ai_analysis_fallbacks import (
    build_batch_brief as _build_batch_brief,
    build_batch_error_item as _build_batch_error_item,
    build_change_alerts as _build_change_alerts,
    build_fallback_analysis as _build_fallback_analysis,
    build_follow_up_fallback as _build_follow_up_fallback,
    build_risk_lights as _build_risk_lights,
    build_source_citation as _build_source_citation,
)
from backend.services.analysis_service.engine.ai_analysis_support import (
    attach_trust_boundary_section as _attach_trust_boundary_section,
)
from backend.services.analysis_service.engine.review_scheduler import review_scheduler

router = APIRouter(prefix="/ai", tags=["AI分析"])

_cache_get = ai_analysis_service._cache_get
_cache_set = ai_analysis_service._cache_set
_get_crawl_status = ai_analysis_service._get_crawl_status


@router.get("/models", response_model=list[AIModelPublicResponse])
async def list_available_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await ai_analysis_service.list_available_models(current_user, db)


@router.get("/model-health")
async def get_model_health(
    refresh: bool = Query(default=False),
    analysis_grade: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await ai_analysis_service.get_model_health(refresh, analysis_grade, current_user, db)


@router.get("/review-scheduler")
async def get_review_scheduler_status(
    current_user: User = Depends(get_current_user),
):
    return review_scheduler.status()


@router.get("/quota", response_model=UserQuotaResponse)
async def get_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await ai_analysis_service.get_quota(current_user, db)


@router.get("/readiness/{symbol}")
async def get_analysis_readiness(
    symbol: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await ai_analysis_service.get_analysis_readiness(symbol, current_user, db)


@router.post("/analyze", response_model=AIAnalysisResponse)
async def analyze_stock(
    request: AIAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await ai_analysis_service.analyze_stock(request, current_user, db)


@router.post("/follow-up", response_model=AIFollowUpResponse)
async def follow_up_analysis(
    request: AIFollowUpRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await ai_analysis_service.follow_up_analysis(request, current_user, db)


@router.post("/batch-summary")
async def batch_summary(
    request: AIBatchSummaryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await ai_analysis_service.batch_summary(request, current_user, db)
