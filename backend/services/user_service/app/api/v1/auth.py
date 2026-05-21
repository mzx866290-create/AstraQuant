"""
认证 API - 注册/登录/Token刷新
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from typing import Optional
import hashlib
import logging
import os
import secrets

from backend.shared.database import get_db
from backend.shared.audit import audit_log
from backend.shared.email import password_reset_email_configured, send_password_reset_email
from backend.shared.models import PasswordResetToken, User, UserQuota
from backend.shared.security import hash_password, verify_password, create_access_token, decode_access_token
from backend.shared.schemas import (
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetResponse,
    UserCreate,
    UserLogin,
    UserPasswordChange,
    UserResponse,
    TokenResponse,
)
from backend.shared.exceptions import raise_unauthorized, raise_bad_request
from backend.shared.auth import get_current_user
from backend.shared.rate_limit import client_ip, enforce_rate_limit, user_identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


def _registration_enabled() -> bool:
    return os.getenv("REGISTRATION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _validate_password(password: str) -> Optional[str]:
    """验证密码强度，返回错误信息或 None"""
    if len(password) < 8:
        return "密码长度不能少于8位"
    if len(password) > 128:
        return "密码长度不能超过128位"
    if not any(c.isupper() for c in password):
        return "密码必须包含至少一个大写字母"
    if not any(c.islower() for c in password):
        return "密码必须包含至少一个小写字母"
    if not any(c.isdigit() for c in password):
        return "密码必须包含至少一个数字"
    return None


def _quota_limits_for_role(role: str | None) -> tuple[int, int]:
    if role == "admin":
        return 1000, 10000
    if role == "premium":
        return 50, 500
    return 10, 100


def _ensure_user_quota(db: Session, user: User) -> None:
    daily_limit, monthly_limit = _quota_limits_for_role(user.role)
    quota = db.query(UserQuota).filter(UserQuota.user_id == user.id).first()
    if quota:
        quota.daily_limit = quota.daily_limit or daily_limit
        quota.monthly_limit = quota.monthly_limit or monthly_limit
        return
    db.add(UserQuota(
        user_id=user.id,
        daily_limit=daily_limit,
        monthly_limit=monthly_limit,
        daily_used=0,
        monthly_used=0,
    ))


PASSWORD_RESET_EXPIRES_MINUTES = int(os.getenv("PASSWORD_RESET_EXPIRES_MINUTES", "30"))
PASSWORD_RESET_GENERIC_MESSAGE = (
    "If the account exists, a password reset email will be sent shortly."
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= _utcnow()


def _find_user_by_identifier(db: Session, identifier: str) -> User | None:
    cleaned = identifier.strip()
    normalized = cleaned.lower()
    return db.query(User).filter(
        or_(
            User.username == cleaned,
            func.lower(User.email) == normalized,
        )
    ).first()


@router.post("/register", response_model=UserResponse)
async def register(data: UserCreate, request: Request, db: Session = Depends(get_db)):
    if not _registration_enabled():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="registration is disabled")

    """用户注册"""
    ip = client_ip(request)
    await enforce_rate_limit(scope="auth:register:ip", identity=ip, limit=3, window_seconds=60, fail_closed=True)
    await enforce_rate_limit(scope="auth:register:ip:day", identity=ip, limit=20, window_seconds=86400, fail_closed=True)

    # 密码强度验证
    pwd_error = _validate_password(data.password)
    if pwd_error:
        raise_bad_request(pwd_error)

    # 检查用户名是否已存在
    existing = db.query(User).filter(
        (User.username == data.username) | (User.email == data.email)
    ).first()
    if existing:
        raise_bad_request("用户名或邮箱已被注册")

    try:
        user = User(
            username=data.username,
            email=data.email,
            password_hash=hash_password(data.password),
            nickname=data.username,
            role="free",
        )
        db.add(user)
        db.flush()
        _ensure_user_quota(db, user)
        audit_log(db, action="auth.register", actor=user, request=request, target=f"user:{user.username}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = str(getattr(exc, "orig", exc)).lower()
        logger.warning("注册写入冲突: username=%s, email=%s, error=%s", data.username, data.email, exc)
        if "user_quotas" in message or "user_quota" in message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="用户配额初始化异常，请稍后重试或联系管理员",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名或邮箱已被注册",
        )
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, request: Request, db: Session = Depends(get_db)):
    """用户登录"""
    ip = client_ip(request)
    login_identifier = data.username.strip()
    normalized_username = login_identifier.lower()
    await enforce_rate_limit(scope="auth:login:ip", identity=ip, limit=5, window_seconds=60, fail_closed=True)
    await enforce_rate_limit(
        scope="auth:login:ip_user",
        identity=f"{ip}:{normalized_username}",
        limit=20,
        window_seconds=900,
        fail_closed=True,
    )

    user = db.query(User).filter(
        or_(
            User.username == login_identifier,
            func.lower(User.email) == normalized_username,
        )
    ).first()
    if not user or not verify_password(data.password, user.password_hash):
        logger.warning(f"登录失败: username={data.username}, ip={request.client.host if request.client else 'unknown'}")
        audit_log(
            db,
            action="auth.login_failed",
            actor=user,
            request=request,
            target=f"username:{data.username}",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码不正确",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        audit_log(db, action="auth.login_blocked", actor=user, request=request, target=f"user:{user.username}")
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用")

    logger.info(f"登录成功: username={data.username}, user_id={user.id}")
    audit_log(db, action="auth.login_success", actor=user, request=request, target=f"user:{user.username}")
    db.commit()
    token = create_access_token({"sub": str(user.id), "username": user.username, "role": user.role})
    return TokenResponse(
        access_token=token,
        expires_in=3600 * 24 * 30,  # 30天
    )


@router.post("/password/forgot", response_model=PasswordResetResponse)
async def request_password_reset(
    data: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    ip = client_ip(request)
    identifier = data.identifier.strip()
    normalized_identifier = identifier.lower()
    await enforce_rate_limit(scope="auth:password_reset:ip", identity=ip, limit=5, window_seconds=900, fail_closed=True)
    await enforce_rate_limit(
        scope="auth:password_reset:identity",
        identity=f"{ip}:{normalized_identifier}",
        limit=3,
        window_seconds=3600,
        fail_closed=True,
    )

    if not password_reset_email_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset email is not configured",
        )

    user = _find_user_by_identifier(db, identifier)
    if not user or not user.is_active:
        logger.info("password reset requested for non-existing or inactive account: %s", identifier)
        return PasswordResetResponse(message=PASSWORD_RESET_GENERIC_MESSAGE)

    raw_token = secrets.token_urlsafe(32)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=_token_hash(raw_token),
        expires_at=_utcnow() + timedelta(minutes=PASSWORD_RESET_EXPIRES_MINUTES),
        requested_ip=ip[:45] if ip else None,
    )
    db.add(reset_token)
    audit_log(db, action="auth.password_reset_requested", actor=user, request=request, target=f"user:{user.username}")
    db.commit()

    try:
        send_password_reset_email(
            to_email=user.email,
            username=user.username,
            token=raw_token,
            expires_minutes=PASSWORD_RESET_EXPIRES_MINUTES,
        )
    except Exception as exc:
        logger.error("password reset email send failed for user_id=%s: %s", user.id, exc)

    return PasswordResetResponse(message=PASSWORD_RESET_GENERIC_MESSAGE)


@router.post("/password/reset", response_model=PasswordResetResponse)
async def reset_password(
    data: PasswordResetConfirm,
    request: Request,
    db: Session = Depends(get_db),
):
    ip = client_ip(request)
    await enforce_rate_limit(scope="auth:password_reset_confirm:ip", identity=ip, limit=10, window_seconds=900, fail_closed=True)

    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == _token_hash(data.token),
    ).first()
    if not reset_token or reset_token.used_at is not None or _is_expired(reset_token.expires_at):
        raise_bad_request("Invalid or expired password reset link")

    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user or not user.is_active:
        raise_bad_request("Invalid or expired password reset link")

    pwd_error = _validate_password(data.new_password)
    if pwd_error:
        raise_bad_request(pwd_error)

    if verify_password(data.new_password, user.password_hash):
        raise_bad_request("New password must be different from the current password")

    now = _utcnow()
    user.password_hash = hash_password(data.new_password)
    active_tokens = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).all()
    for token in active_tokens:
        token.used_at = now

    audit_log(db, action="auth.password_reset_completed", actor=user, request=request, target=f"user:{user.username}")
    db.commit()
    return PasswordResetResponse(message="Password has been reset")


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request, current_user: User = Depends(get_current_user)):
    """获取当前用户信息（需Bearer Token）"""
    await enforce_rate_limit(
        scope="auth:me:user",
        identity=user_identity(current_user),
        limit=120,
        window_seconds=60,
        fail_closed=False,
    )
    return current_user


@router.put("/me/password")
async def change_password(
    data: UserPasswordChange,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改当前用户密码"""
    await enforce_rate_limit(
        scope="auth:password:user",
        identity=user_identity(current_user),
        limit=5,
        window_seconds=300,
        fail_closed=True,
    )

    user = db.query(User).filter(User.id == current_user.id).first()
    if not user or not user.is_active:
        raise_unauthorized()

    if not verify_password(data.current_password, user.password_hash):
        audit_log(db, action="auth.password_change_failed", actor=user, request=request, target=f"user:{user.username}")
        db.commit()
        raise_bad_request("当前密码不正确")

    pwd_error = _validate_password(data.new_password)
    if pwd_error:
        raise_bad_request(pwd_error)

    if verify_password(data.new_password, user.password_hash):
        raise_bad_request("新密码不能和当前密码相同")

    user.password_hash = hash_password(data.new_password)
    audit_log(db, action="auth.password_changed", actor=user, request=request, target=f"user:{user.username}")
    db.commit()
    return {"message": "密码已修改"}
