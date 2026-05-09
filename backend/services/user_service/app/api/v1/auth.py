"""
认证 API - 注册/登录/Token刷新
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
import logging

from backend.shared.database import get_db
from backend.shared.audit import audit_log
from backend.shared.models import User, UserQuota
from backend.shared.security import hash_password, verify_password, create_access_token, decode_access_token
from backend.shared.schemas import UserCreate, UserLogin, UserPasswordChange, UserResponse, TokenResponse
from backend.shared.exceptions import raise_unauthorized, raise_bad_request
from backend.shared.auth import get_current_user
from backend.shared.rate_limit import client_ip, enforce_rate_limit, user_identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


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


@router.post("/register", response_model=UserResponse)
async def register(data: UserCreate, request: Request, db: Session = Depends(get_db)):
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

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        nickname=data.username,
        role="free",
    )
    db.add(user)
    db.flush()
    db.add(UserQuota(
        user_id=user.id,
        daily_limit=10,
        monthly_limit=100,
        daily_used=0,
        monthly_used=0,
    ))
    audit_log(db, action="auth.register", actor=user, request=request, target=f"user:{user.username}")
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, request: Request, db: Session = Depends(get_db)):
    """用户登录"""
    ip = client_ip(request)
    normalized_username = data.username.strip().lower()
    await enforce_rate_limit(scope="auth:login:ip", identity=ip, limit=5, window_seconds=60, fail_closed=True)
    await enforce_rate_limit(
        scope="auth:login:ip_user",
        identity=f"{ip}:{normalized_username}",
        limit=20,
        window_seconds=900,
        fail_closed=True,
    )

    user = db.query(User).filter(User.username == data.username).first()
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
        raise_unauthorized()

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
