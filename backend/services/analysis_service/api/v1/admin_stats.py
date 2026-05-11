"""
使用统计 API - 管理员专用
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List
from datetime import date, datetime, timedelta

from backend.shared.database import get_db
from backend.shared.models import User, AIModel, AIUsageLog, UserQuota
from backend.shared.auth import get_current_user, require_admin
from backend.shared.schemas import AdminStatsResponse
from backend.services.analysis_service.engine.review_scheduler import review_scheduler
from backend.services.analysis_service.engine.review_tracker import (
    build_factor_review_report,
    build_review_readiness,
    build_review_report,
    build_weight_strategy_patch_preview,
    build_weight_adjustment_suggestions,
    apply_strategy_weight_patch_proposal,
    create_strategy_weight_patch_proposal,
    decide_strategy_weight_patch_proposal,
    list_weight_suggestion_audits,
    list_strategy_weight_patch_proposals,
    list_strategy_weight_versions,
    preview_strategy_weight_proposal_impact,
    rollback_strategy_weight_version,
    save_weight_suggestion_audit,
    update_weight_suggestion_audit,
)

router = APIRouter(prefix="/stats", tags=["管理员-统计"])


@router.get("/overview", response_model=AdminStatsResponse)
async def get_overview(
    current_user = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """获取统计概览"""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = today.replace(day=1)

    # 基本统计
    total_users = db.query(User).count()
    active_users_today = db.query(User).filter(User.is_active == True).count()
    total_models = db.query(AIModel).count()
    active_models = db.query(AIModel).filter(AIModel.is_active == True).count()

    # 今日调用
    total_api_calls_today = db.query(func.count(AIUsageLog.id)).filter(
        AIUsageLog.created_at >= today
    ).scalar() or 0

    # 本月调用
    total_api_calls_month = db.query(func.count(AIUsageLog.id)).filter(
        AIUsageLog.created_at >= month_start
    ).scalar() or 0

    # 今日 Token
    total_tokens_today = db.query(func.sum(AIUsageLog.total_tokens)).filter(
        AIUsageLog.created_at >= today
    ).scalar() or 0

    # 本月费用
    total_cost_month = db.query(func.sum(AIUsageLog.cost)).filter(
        AIUsageLog.created_at >= month_start
    ).scalar() or 0.0

    # 各模型调用统计
    calls_by_model = db.query(
        AIModel.name,
        func.count(AIUsageLog.id).label("count"),
        func.sum(AIUsageLog.total_tokens).label("tokens"),
    ).join(AIUsageLog, AIModel.id == AIUsageLog.model_id).group_by(AIModel.name).all()

    # 按日调用统计 (最近30天)
    thirty_days_ago = today - timedelta(days=30)
    calls_by_day_query = db.query(
        func.date(AIUsageLog.created_at).label("date"),
        func.count(AIUsageLog.id).label("count"),
    ).filter(AIUsageLog.created_at >= thirty_days_ago).group_by(func.date(AIUsageLog.created_at)).all()

    # Top 用户
    top_users_query = db.query(
        User.username,
        func.count(AIUsageLog.id).label("count"),
    ).join(AIUsageLog, User.id == AIUsageLog.user_id).group_by(User.username).order_by(
        func.count(AIUsageLog.id).desc()
    ).limit(10).all()

    return AdminStatsResponse(
        total_users=total_users,
        active_users_today=active_users_today,
        total_models=total_models,
        active_models=active_models,
        total_api_calls_today=total_api_calls_today,
        total_api_calls_month=total_api_calls_month,
        total_tokens_today=total_tokens_today,
        total_cost_month=total_cost_month or 0.0,
        calls_by_model=[
            {"model_name": name, "count": count, "tokens": int(tokens or 0)}
            for name, count, tokens in calls_by_model
        ],
        calls_by_day=[
            {"date": str(date), "count": count}
            for date, count in calls_by_day_query
        ],
        top_users=[
            {"username": username, "count": count}
            for username, count in top_users_query
        ],
    )


@router.get("/calls-by-day")
async def get_calls_by_day(
    days: int = Query(default=30, ge=1, le=90),
    current_user = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """按日统计调用量"""
    from datetime import datetime, timedelta
    start_date = datetime.now() - timedelta(days=days)

    results = db.query(
        func.date(AIUsageLog.created_at).label("date"),
        func.count(AIUsageLog.id).label("count"),
        func.sum(AIUsageLog.total_tokens).label("tokens"),
        func.sum(AIUsageLog.cost).label("cost"),
    ).filter(AIUsageLog.created_at >= start_date).group_by(
        func.date(AIUsageLog.created_at)
    ).order_by(func.date(AIUsageLog.created_at)).all()

    return [
        {"date": str(r.date), "count": r.count, "tokens": int(r.tokens or 0), "cost": float(r.cost or 0)}
        for r in results
    ]


@router.get("/calls-by-model")
async def get_calls_by_model(
    current_user = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """按模型统计调用量"""
    results = db.query(
        AIModel.id,
        AIModel.name,
        AIModel.provider,
        func.count(AIUsageLog.id).label("count"),
        func.sum(AIUsageLog.total_tokens).label("tokens"),
        func.sum(AIUsageLog.cost).label("cost"),
    ).outerjoin(AIUsageLog, AIModel.id == AIUsageLog.model_id).group_by(
        AIModel.id, AIModel.name, AIModel.provider
    ).all()

    return [
        {
            "model_id": r.id,
            "model_name": r.name,
            "provider": r.provider,
            "count": r.count or 0,
            "tokens": int(r.tokens or 0),
            "cost": float(r.cost or 0),
        }
        for r in results
    ]


@router.get("/top-users")
async def get_top_users(
    limit: int = Query(default=10, ge=1, le=100),
    current_user = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """Top 用户排行"""
    results = db.query(
        User.id,
        User.username,
        func.count(AIUsageLog.id).label("count"),
        func.sum(AIUsageLog.total_tokens).label("tokens"),
        func.sum(AIUsageLog.cost).label("cost"),
    ).join(AIUsageLog, User.id == AIUsageLog.user_id).group_by(
        User.id, User.username
    ).order_by(func.count(AIUsageLog.id).desc()).limit(limit).all()

    return [
        {"user_id": r.id, "username": r.username, "count": r.count, "tokens": int(r.tokens or 0), "cost": float(r.cost or 0)}
        for r in results
    ]


@router.get("/cost-trend")
async def get_cost_trend(
    days: int = Query(default=30, ge=1, le=365),
    current_user = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """费用趋势（按日/按月）"""
    from datetime import datetime, timedelta
    start_date = datetime.now() - timedelta(days=days)

    results = db.query(
        func.date(AIUsageLog.created_at).label("date"),
        func.sum(AIUsageLog.cost).label("cost"),
    ).filter(AIUsageLog.created_at >= start_date).group_by(
        func.date(AIUsageLog.created_at)
    ).order_by(func.date(AIUsageLog.created_at)).all()

    return [
        {"date": str(r.date), "cost": float(r.cost or 0)}
        for r in results
    ]


@router.get("/review-scheduler")
async def get_review_scheduler(
    current_user=Depends(require_admin()),
):
    """Get research review scheduler status."""
    return review_scheduler.status()


@router.get("/review-readiness")
async def get_review_readiness(
    review_date: date | None = Query(default=None),
    offsets: str = Query(default="T+1,T+5,T+20"),
    current_user=Depends(require_admin()),
):
    """Get production readiness state for research review loop."""
    offset_list = tuple(item.strip() for item in offsets.split(",") if item.strip())
    invalid_offsets = [offset for offset in offset_list if offset not in {"T+1", "T+5", "T+20"}]
    if not offset_list or invalid_offsets:
        raise HTTPException(status_code=400, detail="offsets only accepts: T+1, T+5, T+20")
    return build_review_readiness(review_date=review_date, offsets=offset_list)


@router.get("/review-report")
async def get_review_report(
    snapshot_from: date | None = Query(default=None),
    snapshot_to: date | None = Query(default=None),
    current_user=Depends(require_admin()),
):
    """Get aggregated research review report."""
    if snapshot_from and snapshot_to and snapshot_from > snapshot_to:
        raise HTTPException(status_code=400, detail="snapshot_from must be earlier than or equal to snapshot_to")
    return build_review_report(snapshot_from=snapshot_from, snapshot_to=snapshot_to)


@router.get("/review-factor-report")
async def get_review_factor_report(
    snapshot_from: date | None = Query(default=None),
    snapshot_to: date | None = Query(default=None),
    current_user=Depends(require_admin()),
):
    """Get aggregated research review factor attribution report."""
    if snapshot_from and snapshot_to and snapshot_from > snapshot_to:
        raise HTTPException(status_code=400, detail="snapshot_from must be earlier than or equal to snapshot_to")
    return build_factor_review_report(snapshot_from=snapshot_from, snapshot_to=snapshot_to)


@router.get("/review-weight-suggestions")
async def get_review_weight_suggestions(
    min_reviews: int = Query(default=3, ge=1, le=100),
    snapshot_from: date | None = Query(default=None),
    snapshot_to: date | None = Query(default=None),
    save_audit: bool = Query(default=False),
    current_user=Depends(require_admin()),
):
    """Get conservative factor weight adjustment suggestions."""
    if snapshot_from and snapshot_to and snapshot_from > snapshot_to:
        raise HTTPException(status_code=400, detail="snapshot_from must be earlier than or equal to snapshot_to")
    result = build_weight_adjustment_suggestions(
        min_reviews=min_reviews,
        snapshot_from=snapshot_from,
        snapshot_to=snapshot_to,
    )
    if save_audit:
        result = dict(result)
        result["audit_id"] = save_weight_suggestion_audit(
            result,
            min_reviews=min_reviews,
            snapshot_from=snapshot_from,
            snapshot_to=snapshot_to,
        )
    return result


@router.get("/review-weight-suggestion-audits")
async def get_review_weight_suggestion_audits(
    limit: int = Query(default=20, ge=1, le=100),
    current_user=Depends(require_admin()),
):
    """List recent weight suggestion audit records."""
    return list_weight_suggestion_audits(limit=limit)


@router.patch("/review-weight-suggestion-audits/{audit_id}")
async def patch_review_weight_suggestion_audit(
    audit_id: int,
    body: dict,
    current_user=Depends(require_admin()),
):
    """Update a weight suggestion audit decision."""
    accepted_provided = "accepted" in body
    accepted = body.get("accepted") if "accepted" in body else None
    notes = body.get("notes") if "notes" in body else None
    updated = update_weight_suggestion_audit(
        audit_id,
        accepted=accepted,
        notes=notes,
        accepted_by=getattr(current_user, "id", None),
        accepted_provided=accepted_provided,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="audit not found")
    return updated


@router.get("/review-weight-suggestion-audits/{audit_id}/strategy-patch")
async def get_review_weight_suggestion_strategy_patch(
    audit_id: int,
    strategy_id: str = Query(default="retail_small"),
    step: float = Query(default=0.03, ge=0, le=1),
    max_delta: float = Query(default=0.08, ge=0, le=1),
    current_user=Depends(require_admin()),
):
    """Preview a strategy weight patch from an accepted audit without writing files."""
    return build_weight_strategy_patch_preview(
        audit_id,
        strategy_id=strategy_id,
        step=step,
        max_delta=max_delta,
    )


@router.post("/review-weight-suggestion-audits/{audit_id}/strategy-patch-proposals")
async def post_strategy_weight_patch_proposal(
    audit_id: int,
    body: dict | None = None,
    current_user=Depends(require_admin()),
):
    """Create a pending strategy weight patch proposal from an accepted audit."""
    payload = body or {}
    return create_strategy_weight_patch_proposal(
        audit_id,
        strategy_id=str(payload.get("strategy_id") or "retail_small"),
        step=float(payload.get("step") or 0.03),
        max_delta=float(payload.get("max_delta") or 0.08),
        created_by=getattr(current_user, "id", None),
        notes=payload.get("notes"),
    )


@router.get("/strategy-weight-patch-proposals")
async def get_strategy_weight_patch_proposals(
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    current_user=Depends(require_admin()),
):
    """List pending/decided strategy weight patch proposals."""
    return list_strategy_weight_patch_proposals(limit=limit, status=status)


@router.patch("/strategy-weight-patch-proposals/{proposal_id}")
async def patch_strategy_weight_patch_proposal(
    proposal_id: int,
    body: dict,
    current_user=Depends(require_admin()),
):
    """Approve, reject, or reset a strategy weight patch proposal. This does not write strategy files."""
    updated = decide_strategy_weight_patch_proposal(
        proposal_id,
        status=str(body.get("status") or ""),
        decided_by=getattr(current_user, "id", None),
        notes=body.get("notes"),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return updated


@router.post("/strategy-weight-patch-proposals/{proposal_id}/apply")
async def post_apply_strategy_weight_patch_proposal(
    proposal_id: int,
    body: dict | None = None,
    current_user=Depends(require_admin()),
):
    """Apply an approved strategy weight patch proposal to the JSON strategy config."""
    payload = body or {}
    updated = apply_strategy_weight_patch_proposal(
        proposal_id,
        applied_by=getattr(current_user, "id", None),
        notes=payload.get("notes"),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    if updated.get("status") != "applied":
        raise HTTPException(status_code=409, detail=updated)
    return updated


@router.get("/strategy-weight-patch-proposals/{proposal_id}/impact-preview")
async def get_strategy_weight_patch_proposal_impact_preview(
    proposal_id: int,
    market: str = Query(default="ALL"),
    limit: int = Query(default=20, ge=1, le=50),
    candidate_limit: int = Query(default=60, ge=1, le=200),
    concurrency: int = Query(default=8, ge=1, le=32),
    current_user=Depends(require_admin()),
):
    """Preview recommendation ranking impact of a strategy weight proposal without applying it."""
    result = await preview_strategy_weight_proposal_impact(
        proposal_id,
        market=market,
        limit=limit,
        candidate_limit=candidate_limit,
        concurrency=concurrency,
    )
    if result.get("status") == "proposal_not_found":
        raise HTTPException(status_code=404, detail="proposal not found")
    return result


@router.get("/strategy-weight-versions")
async def get_strategy_weight_versions(
    strategy_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user=Depends(require_admin()),
):
    """List applied strategy weight versions for rollback/audit."""
    return list_strategy_weight_versions(strategy_id=strategy_id, limit=limit)


@router.post("/strategy-weight-versions/{version_id}/rollback")
async def post_rollback_strategy_weight_version(
    version_id: int,
    body: dict | None = None,
    current_user=Depends(require_admin()),
):
    """Rollback a strategy's weights to the before snapshot of a version."""
    payload = body or {}
    updated = rollback_strategy_weight_version(
        version_id,
        rolled_back_by=getattr(current_user, "id", None),
        notes=payload.get("notes"),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="version not found")
    if updated.get("rollback_error"):
        raise HTTPException(status_code=409, detail=updated)
    return updated


@router.post("/review-scheduler/run-once")
async def run_review_scheduler_once(
    review_date: date | None = Query(default=None),
    current_user=Depends(require_admin()),
):
    """Run pending research reviews once."""
    return await review_scheduler.run_once(review_date=review_date)
