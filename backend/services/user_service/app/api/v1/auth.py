"""
认证 API - 注册/登录/Token刷新
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
import logging

from backend.shared.database import get_db
from backend.shared.models import User
from backend.shared.security import hash_password, verify_password, create_access_token, decode_access_token
from backend.shared.schemas import UserCreate, UserLogin, UserResponse, TokenResponse
from backend.shared.exceptions import raise_unauthorized, raise_bad_request
from backend.shared.auth import get_current_user

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
async def register(data: UserCreate, db: Session = Depends(get_db)):
    """用户注册"""
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
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, request: Request, db: Session = Depends(get_db)):
    """用户登录"""
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.password_hash):
        logger.warning(f"登录失败: username={data.username}, ip={request.client.host if request.client else 'unknown'}")
        raise_unauthorized()

    logger.info(f"登录成功: username={data.username}, user_id={user.id}")
    token = create_access_token({"sub": str(user.id), "username": user.username, "role": user.role})
    return TokenResponse(
        access_token=token,
        expires_in=3600 * 24 * 30,  # 30天
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息（需Bearer Token）"""
    return current_user
