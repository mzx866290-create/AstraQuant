"""
用户管理 API - 管理员专用
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List

from backend.shared.audit import audit_log
from backend.shared.database import get_db
from backend.shared.models import (
    AIModel,
    AIUsageLog,
    PriceAlert,
    User,
    UserActivityLog,
    UserQuota,
    Watchlist,
    WatchlistItem,
)
from backend.shared.auth import require_admin
from backend.shared.schemas import AdminUserResponse, AdminUserUpdate, UserQuotaResponse

router = APIRouter(prefix="/users", tags=["管理员-用户管理"])


class AdminUserListResponse(BaseModel):
    items: List[AdminUserResponse]
    total: int
    skip: int
    limit: int


@router.get("")
async def list_users(
    skip: int = 0,
    limit: int = 100,
    paged: bool = False,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """获取用户列表"""
    query = db.query(User)

    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if search:
        query = query.filter(
            (User.username.contains(search)) | (User.email.contains(search))
        )

    total = query.count()
    users = query.order_by(User.id).offset(skip).limit(limit).all()

    # 获取配额信息
    result = []
    for user in users:
        quota = db.query(UserQuota).filter(UserQuota.user_id == user.id).first()
        user_data = AdminUserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            nickname=user.nickname,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
            daily_limit=quota.daily_limit if quota else 10,
            monthly_limit=quota.monthly_limit if quota else 100,
            daily_used=quota.daily_used if quota else 0,
            monthly_used=quota.monthly_used if quota else 0,
        )
        result.append(user_data)

    if paged:
        return AdminUserListResponse(items=result, total=total, skip=skip, limit=limit)
    return result


@router.get("/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """获取指定用户详情"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    quota = db.query(UserQuota).filter(UserQuota.user_id == user.id).first()
    return AdminUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        nickname=user.nickname,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        daily_limit=quota.daily_limit if quota else 10,
        monthly_limit=quota.monthly_limit if quota else 100,
        daily_used=quota.daily_used if quota else 0,
        monthly_used=quota.monthly_used if quota else 0,
    )


@router.put("/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: int,
    data: AdminUserUpdate,
    request: Request,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """更新用户信息"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active

    audit_log(
        db,
        action="admin.user_update",
        actor=current_user,
        request=request,
        target=f"user:{user_id}:role={data.role}:active={data.is_active}",
    )
    db.commit()
    db.refresh(user)

    # 更新配额
    quota = db.query(UserQuota).filter(UserQuota.user_id == user.id).first()
    if data.daily_limit is not None and quota:
        quota.daily_limit = data.daily_limit
    if data.monthly_limit is not None and quota:
        quota.monthly_limit = data.monthly_limit

    db.commit()

    return await get_user(user_id, current_user, db)


@router.put("/{user_id}/quota", response_model=UserQuotaResponse)
async def update_quota(
    user_id: int,
    data: AdminUserUpdate,
    request: Request,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """更新用户配额"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()
    if not quota:
        quota = UserQuota(
            user_id=user_id,
            daily_limit=data.daily_limit or 10,
            monthly_limit=data.monthly_limit or 100,
        )
        db.add(quota)
    else:
        if data.daily_limit is not None:
            quota.daily_limit = data.daily_limit
        if data.monthly_limit is not None:
            quota.monthly_limit = data.monthly_limit

    audit_log(
        db,
        action="admin.user_quota_update",
        actor=current_user,
        request=request,
        target=f"user:{user_id}:daily={data.daily_limit}:monthly={data.monthly_limit}",
    )
    db.commit()
    db.refresh(quota)

    return UserQuotaResponse(
        user_id=quota.user_id,
        daily_limit=quota.daily_limit,
        monthly_limit=quota.monthly_limit,
        daily_used=quota.daily_used,
        monthly_used=quota.monthly_used,
        daily_remaining=max(0, quota.daily_limit - quota.daily_used),
        monthly_remaining=max(0, quota.monthly_limit - quota.monthly_used),
    )


@router.post("/{user_id}/reset-quota")
async def reset_quota(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """重置用户配额已使用次数"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()
    if quota:
        quota.daily_used = 0
        quota.monthly_used = 0
        audit_log(db, action="admin.user_quota_reset", actor=current_user, request=request, target=f"user:{user_id}")
        db.commit()

    return {"message": "配额已重置"}


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """删除用户（管理员专用）"""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="不能删除管理员账号")

    target = f"user:{user_id}:{user.username}"
    watchlist_ids = [item.id for item in db.query(Watchlist.id).filter(Watchlist.user_id == user_id).all()]
    if watchlist_ids:
        db.query(WatchlistItem).filter(WatchlistItem.watchlist_id.in_(watchlist_ids)).delete(synchronize_session=False)
    db.query(Watchlist).filter(Watchlist.user_id == user_id).delete(synchronize_session=False)
    db.query(PriceAlert).filter(PriceAlert.user_id == user_id).delete(synchronize_session=False)
    db.query(UserQuota).filter(UserQuota.user_id == user_id).delete(synchronize_session=False)
    db.query(UserActivityLog).filter(UserActivityLog.user_id == user_id).delete(synchronize_session=False)
    db.query(AIUsageLog).filter(AIUsageLog.user_id == user_id).delete(synchronize_session=False)
    db.query(AIModel).filter(AIModel.created_by == user_id).update({"created_by": None}, synchronize_session=False)
    db.delete(user)
    audit_log(db, action="admin.user_delete", actor=current_user, request=request, target=target)
    db.commit()
    return {"message": f"用户 {user.username} 已删除"}
