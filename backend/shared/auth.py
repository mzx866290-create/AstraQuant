"""Authentication, authorization, quota, and AI key helpers."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import is_production
from .database import SessionLocal
from .models import User, UserQuota
from .security import decode_access_token

logger = logging.getLogger(__name__)

_warned_derived_api_key_storage = False
_warned_plain_api_key_read = False
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").lower() != "false"

security = HTTPBearer(auto_error=False)


def _allow_dev_admin() -> bool:
    return not is_production() and os.getenv("ALLOW_DEV_ADMIN", "false").lower() == "true"


def _get_or_create_dev_user() -> User:
    db = SessionLocal()
    try:
        dev_role = "admin" if _allow_dev_admin() else "free"
        user = db.query(User).filter(User.username == "dev").first()
        if not user:
            from .security import hash_password

            user = User(
                username="dev",
                email="dev@localhost",
                password_hash=hash_password("dev"),
                nickname="dev-user",
                role=dev_role,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        elif user.role != dev_role:
            user.role = dev_role
            db.commit()
            db.refresh(user)

        quota = db.query(UserQuota).filter(UserQuota.user_id == user.id).first()
        if not quota:
            quota = UserQuota(user_id=user.id, daily_limit=999999, monthly_limit=999999)
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


def get_token_from_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = None,
    auth_header: Optional[str] = None,
) -> Optional[str]:
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
    if not AUTH_REQUIRED:
        if is_production():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="production environment forbids disabling authentication",
            )
        return _get_or_create_dev_user()

    token = get_token_from_auth(credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token payload",
        )

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token payload",
        )

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="user not found",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="user is disabled",
            )
        return user
    finally:
        db.close()


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[User]:
    if not AUTH_REQUIRED:
        if is_production():
            return None
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

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == uid).first()
        return user if user and user.is_active else None
    except Exception:
        return None
    finally:
        db.close()


def require_role(*allowed_roles: str):
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if not AUTH_REQUIRED and set(allowed_roles) == {"admin"} and not _allow_dev_admin():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="dev auth mode does not grant admin access; set ALLOW_DEV_ADMIN=true for local debugging",
            )
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires {'/'.join(allowed_roles)} role",
            )
        return current_user

    return role_checker


def require_admin():
    return require_role("admin")


def require_active_user():
    return require_role("free", "premium", "admin")


def get_user_quota(user_id: int) -> UserQuota:
    db = SessionLocal()
    try:
        quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()
        if not quota:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="user not found")

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
    quota = get_user_quota(user_id)
    now = datetime.now(timezone.utc)

    if quota.last_reset_daily and quota.last_reset_daily.replace(tzinfo=timezone.utc) < now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ):
        quota.daily_used = 0
        quota.last_reset_daily = now

    if quota.last_reset_monthly and quota.last_reset_monthly.replace(tzinfo=timezone.utc) < now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ):
        quota.monthly_used = 0
        quota.last_reset_monthly = now

    if quota.daily_used >= quota.daily_limit:
        return False, f"daily quota exhausted ({quota.daily_limit}/{quota.daily_limit})"

    if quota.monthly_used >= quota.monthly_limit:
        return False, f"monthly quota exhausted ({quota.monthly_limit}/{quota.monthly_limit})"

    return True, ""


def increment_quota(user_id: int):
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


def _configured_ai_encryption_key() -> str:
    return os.getenv("AI_ENCRYPTION_KEY", "").strip()


def _derived_ai_encryption_key() -> str:
    global _warned_derived_api_key_storage

    seed = os.getenv("JWT_SECRET", "").strip() or os.getenv("APP_ENV", "development")
    derived = base64.urlsafe_b64encode(
        hashlib.sha256(f"ai-key:{seed}".encode("utf-8")).digest()
    ).decode("ascii")

    if not _warned_derived_api_key_storage:
        logger.warning(
            "AI_ENCRYPTION_KEY is not set; deriving a local-only fallback key from JWT_SECRET for non-production use"
        )
        _warned_derived_api_key_storage = True
    return derived


def _get_ai_fernet(*, require_explicit_key: bool):
    raw_key = _configured_ai_encryption_key()
    if not raw_key:
        if require_explicit_key:
            raise RuntimeError("AI_ENCRYPTION_KEY is required before storing AI API keys in production")
        raw_key = _derived_ai_encryption_key()

    from cryptography.fernet import Fernet

    try:
        return Fernet(raw_key.encode())
    except Exception as exc:
        if _configured_ai_encryption_key():
            raise RuntimeError("AI_ENCRYPTION_KEY is invalid; expected a valid Fernet key") from exc
        raise RuntimeError("failed to derive a usable fallback AI encryption key") from exc


def encrypt_api_key(api_key: str) -> str:
    f = _get_ai_fernet(require_explicit_key=is_production())
    return f.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    f = _get_ai_fernet(require_explicit_key=is_production())
    try:
        return f.decrypt(encrypted_key.encode()).decode()
    except Exception as exc:
        if is_production():
            raise RuntimeError("AI_ENCRYPTION_KEY is required before reading AI API keys in production") from exc
        if encrypted_key.startswith("gAAAA"):
            raise RuntimeError(
                "stored AI API key is encrypted but cannot be decrypted; configure the original AI_ENCRYPTION_KEY or re-save the key"
            ) from exc
        if _configured_ai_encryption_key():
            raise RuntimeError(
                "stored AI API key could not be decrypted with the current AI_ENCRYPTION_KEY"
            ) from exc
        global _warned_plain_api_key_read
        if not _warned_plain_api_key_read:
            logger.warning(
                "Encountered a legacy plaintext AI API key; reading it without decryption in non-production"
            )
            _warned_plain_api_key_read = True
        return encrypted_key
