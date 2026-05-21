"""
调用日志 API - 管理员专用
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import Optional
import csv
import io
from datetime import datetime

from backend.shared.database import get_db
from backend.shared.models import User, AIModel, AIUsageLog, UserActivityLog
from backend.shared.auth import get_current_user, require_admin
from backend.shared.schemas import AIUsageLogResponse, UserActivityLogResponse

router = APIRouter(prefix="/logs", tags=["管理员-日志"])


@router.get("", response_model=list[AIUsageLogResponse])
async def list_logs(
    skip: int = 0,
    limit: int = 20,
    user_id: Optional[int] = None,
    model_id: Optional[int] = None,
    status: Optional[str] = None,
    stock_symbol: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """获取调用日志列表"""
    query = db.query(AIUsageLog)

    if user_id:
        query = query.filter(AIUsageLog.user_id == user_id)
    if model_id:
        query = query.filter(AIUsageLog.model_id == model_id)
    if status:
        query = query.filter(AIUsageLog.status == status)
    if stock_symbol:
        query = query.filter(AIUsageLog.stock_symbol.contains(stock_symbol))
    if date_from:
        query = query.filter(AIUsageLog.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(AIUsageLog.created_at <= datetime.fromisoformat(date_to))

    logs = query.order_by(desc(AIUsageLog.created_at)).offset(skip).limit(limit).all()

    # 补充用户名和模型名
    result = []
    for log in logs:
        user = db.query(User).filter(User.id == log.user_id).first()
        model = db.query(AIModel).filter(AIModel.id == log.model_id).first()
        result.append(AIUsageLogResponse(
            id=log.id,
            user_id=log.user_id,
            username=user.username if user else None,
            model_id=log.model_id,
            model_name=model.name if model else None,
            stock_symbol=log.stock_symbol,
            prompt_tokens=log.prompt_tokens,
            completion_tokens=log.completion_tokens,
            total_tokens=log.total_tokens,
            cost=log.cost,
            status=log.status,
            error_message=log.error_message,
            response_time_ms=log.response_time_ms,
            created_at=log.created_at,
        ))

    return result


@router.get("/activity", response_model=list[UserActivityLogResponse])
async def list_activity_logs(
    skip: int = 0,
    limit: int = 20,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    target: Optional[str] = None,
    ip_address: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """List user activity audit logs for admins."""
    query = db.query(UserActivityLog)

    if user_id:
        query = query.filter(UserActivityLog.user_id == user_id)
    if action:
        query = query.filter(UserActivityLog.action.contains(action))
    if target:
        query = query.filter(UserActivityLog.target.contains(target))
    if ip_address:
        query = query.filter(UserActivityLog.ip_address.contains(ip_address))
    if date_from:
        query = query.filter(UserActivityLog.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(UserActivityLog.created_at <= datetime.fromisoformat(date_to))

    logs = query.order_by(desc(UserActivityLog.created_at)).offset(skip).limit(limit).all()

    result = []
    for log in logs:
        user = db.query(User).filter(User.id == log.user_id).first() if log.user_id else None
        result.append(UserActivityLogResponse(
            id=log.id,
            user_id=log.user_id,
            username=user.username if user else None,
            action=log.action,
            target=log.target,
            ip_address=log.ip_address,
            user_agent=log.user_agent,
            created_at=log.created_at,
        ))

    return result


@router.get("/export")
async def export_logs(
    user_id: Optional[int] = None,
    model_id: Optional[int] = None,
    status: Optional[str] = None,
    stock_symbol: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """导出日志为 CSV"""
    query = db.query(AIUsageLog)

    if user_id:
        query = query.filter(AIUsageLog.user_id == user_id)
    if model_id:
        query = query.filter(AIUsageLog.model_id == model_id)
    if status:
        query = query.filter(AIUsageLog.status == status)
    if stock_symbol:
        query = query.filter(AIUsageLog.stock_symbol.contains(stock_symbol))
    if date_from:
        query = query.filter(AIUsageLog.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(AIUsageLog.created_at <= datetime.fromisoformat(date_to))

    logs = query.order_by(desc(AIUsageLog.created_at)).limit(10000).all()

    # 生成 CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "用户", "模型", "股票", "输入Token", "输出Token", "总Token", "费用(USD)", "状态", "耗时(ms)", "时间"])

    for log in logs:
        user = db.query(User).filter(User.id == log.user_id).first()
        model = db.query(AIModel).filter(AIModel.id == log.model_id).first()
        writer.writerow([
            log.id,
            user.username if user else log.user_id,
            model.name if model else log.model_id,
            log.stock_symbol or "",
            log.prompt_tokens,
            log.completion_tokens,
            log.total_tokens,
            f"{log.cost:.6f}",
            log.status,
            log.response_time_ms,
            log.created_at.isoformat() if log.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ai_usage_logs.csv"},
    )


@router.get("/count")
async def get_log_count(
    user_id: Optional[int] = None,
    model_id: Optional[int] = None,
    status: Optional[str] = None,
    stock_symbol: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """获取日志总数（用于分页）"""
    query = db.query(func.count(AIUsageLog.id))

    if user_id:
        query = query.filter(AIUsageLog.user_id == user_id)
    if model_id:
        query = query.filter(AIUsageLog.model_id == model_id)
    if status:
        query = query.filter(AIUsageLog.status == status)
    if stock_symbol:
        query = query.filter(AIUsageLog.stock_symbol.contains(stock_symbol))
    if date_from:
        query = query.filter(AIUsageLog.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(AIUsageLog.created_at <= datetime.fromisoformat(date_to))

    return {"total": query.scalar() or 0}


@router.get("/activity/count")
async def get_activity_log_count(
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    target: Optional[str] = None,
    ip_address: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """Get user activity audit log count for pagination."""
    query = db.query(func.count(UserActivityLog.id))

    if user_id:
        query = query.filter(UserActivityLog.user_id == user_id)
    if action:
        query = query.filter(UserActivityLog.action.contains(action))
    if target:
        query = query.filter(UserActivityLog.target.contains(target))
    if ip_address:
        query = query.filter(UserActivityLog.ip_address.contains(ip_address))
    if date_from:
        query = query.filter(UserActivityLog.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(UserActivityLog.created_at <= datetime.fromisoformat(date_to))

    return {"total": query.scalar() or 0}



@router.post("/news-enrich/trigger")
async def trigger_news_enrich(
    trade_date: str = None,
    current_user=Depends(require_admin()),
):
    """手动触发新闻增强（管理员用）"""
    from backend.services.analysis_service.engine.news_enricher import enrich_with_news
    result = await enrich_with_news(trade_date)
    return result
