"""
认证中间件 + 角色权限守卫
设置 AUTH_REQUIRED=false 可跳过 JWT 认证（开发/测试用）
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, List
import os
import logging

from .security import decode_access_token, create_access_token
from .database import SessionLocal
from .models import User, UserQuota

logger = logging.getLogger(__name__)

# 安全警告：生产环境必须通过环境变量配置
AI_ENCRYPTION_KEY = os.getenv("AI_ENCRYPTION_KEY", "")
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").lower() != "false"

security = HTTPBearer(auto_error=False)


def _get_or_create_dev_user() -> User:
    """获取或创建开发模式默认用户"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "dev").first()
        if not user:
            from .security import hash_password
            user = User(
                username="dev",
                email="dev@localhost",
                password_hash=hash_password("dev"),
                nickname="开发用户",
                role="admin",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        # 给 dev 用户无限配额
        quota = db.query(UserQuota).filter(UserQuota.user_id == user.id).first()
        if not quota:
            quota = UserQuota(
                user_id=user.id,
                daily_limit=999999,
                monthly_limit=999999,
            )
            db.add(quota)
            db.commit()
        elif quota.daily_limit < 999999:
            quota.daily_limit = 999999
            quota.monthly_limit = 999999
            quota.daily_used = 0
            quota.monthly_used = 0
            db.commit()
        return user
    finally:
        db.close()


def get_token_from_auth(credentials: Optional[HTTPAuthorizationCredentials] = None, auth_header: Optional[str] = None) -> Optional[str]:
    """从 HTTPBearer 或 Authorization header 获取 token"""
    if credentials:
        return credentials.credentials
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
    return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> User:
    """从 JWT 获取当前用户 (依赖注入)。AUTH_REQUIRED=false 时返回默认 dev 用户"""
    if not AUTH_REQUIRED:
        return _get_or_create_dev_user()

    token = get_token_from_auth(credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌格式错误",
        )

    db = SessionLocal()
    try:
        try:
            uid = int(user_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="令牌格式错误",
            )
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用户已被禁用",
            )
        return user
    finally:
        db.close()


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[User]:
    """可选的当前用户 (未登录返回 None，AUTH_REQUIRED=false 时返回 dev)"""
    if not AUTH_REQUIRED:
        return _get_or_create_dev_user()

    token = get_token_from_auth(credentials)
    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
        return user if user and user.is_active else None
    except Exception:
        return None
    finally:
        db.close()


def require_role(*allowed_roles: str):
    """角色守卫装饰器 - 要求用户具有指定角色之一"""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要 {'/'.join(allowed_roles)} 权限",
            )
        return current_user
    return role_checker


def require_admin():
    """管理员专用守卫"""
    return require_role("admin")


def require_active_user():
    """活跃用户守卫"""
    return require_role("free", "premium", "admin")


def get_user_quota(user_id: int) -> UserQuota:
    """获取用户配额"""
    db = SessionLocal()
    try:
        quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()
        if not quota:
            # 创建默认配额
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

            role = user.role or "free"
            daily_limit = 1000 if role == "admin" else (50 if role == "premium" else 10)
            monthly_limit = 10000 if role == "admin" else (500 if role == "premium" else 100)

            quota = UserQuota(
                user_id=user_id,
                daily_limit=daily_limit,
                monthly_limit=monthly_limit,
            )
            db.add(quota)
            db.commit()
            db.refresh(quota)
        return quota
    finally:
        db.close()


def check_quota_available(user_id: int) -> tuple[bool, str]:
    """检查用户是否有可用配额"""
    from datetime import datetime, timezone

    quota = get_user_quota(user_id)
    now = datetime.now(timezone.utc)

    # 重置每日配额
    if quota.last_reset_daily and quota.last_reset_daily.replace(tzinfo=timezone.utc) < now.replace(hour=0, minute=0, second=0, microsecond=0):
        quota.daily_used = 0
        quota.last_reset_daily = now

    # 重置每月配额
    if quota.last_reset_monthly and quota.last_reset_monthly.replace(tzinfo=timezone.utc) < now.replace(day=1, hour=0, minute=0, second=0, microsecond=0):
        quota.monthly_used = 0
        quota.last_reset_monthly = now

    # 检查配额
    if quota.daily_used >= quota.daily_limit:
        return False, f"今日调用次数已用完 ( {quota.daily_limit}/{quota.daily_limit} )"

    if quota.monthly_used >= quota.monthly_limit:
        return False, f"本月调用次数已用完 ( {quota.monthly_limit}/{quota.monthly_limit} )"

    return True, ""


def increment_quota(user_id: int):
    """增加配额使用次数"""
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()
        if quota:
            quota.daily_used += 1
            quota.monthly_used += 1
            quota.last_reset_daily = datetime.now(timezone.utc)
            quota.last_reset_monthly = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def encrypt_api_key(api_key: str) -> str:
    """加密 API Key (Fernet 对称加密)"""
    if not AI_ENCRYPTION_KEY:
        import logging
        logging.getLogger(__name__).warning(
            "AI_ENCRYPTION_KEY 未设置，API Key 将以明文存储。生产环境必须配置此变量。"
        )
        return api_key

    from cryptography.fernet import Fernet
    f = Fernet(AI_ENCRYPTION_KEY.encode())
    return f.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """解密 API Key"""
    if not AI_ENCRYPTION_KEY:
        import logging
        logging.getLogger(__name__).warning(
            "AI_ENCRYPTION_KEY 未设置，无法解密 API Key。"
        )
        return encrypted_key

    from cryptography.fernet import Fernet
    f = Fernet(AI_ENCRYPTION_KEY.encode())
    return f.decrypt(encrypted_key.encode()).decode()