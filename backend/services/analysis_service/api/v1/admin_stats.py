"""
使用统计 API - 管理员专用
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta

from backend.shared.database import get_db
from backend.shared.models import User, AIModel, AIUsageLog, UserQuota
from backend.shared.auth import get_current_user, require_admin
from backend.shared.schemas import AdminStatsResponse

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