"""Runtime configuration guards shared by backend services."""
from __future__ import annotations

import base64
import os
from typing import Iterable


DEFAULT_JWT_SECRET = "your-super-secret-jwt-key-change-in-production"
DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me"
PLACEHOLDER_VALUES = {
    "",
    "admin",
    "admin123",
    "changeme",
    "change_me",
    "password",
    "password123",
    "production_password_change_me",
    "test-ai-key",
    "your_tushare_token_here",
    DEFAULT_JWT_SECRET,
    DEV_JWT_SECRET,
}


def app_env() -> str:
    return os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development"


def is_production() -> bool:
    return app_env().lower() in {"prod", "production"}


def is_placeholder(value: str | None, extra: Iterable[str] = ()) -> bool:
    if value is None:
        return True
    normalized = value.strip()
    return normalized in PLACEHOLDER_VALUES or normalized in set(extra)


def looks_like_fernet_key(value: str | None) -> bool:
    if not value:
        return False
    try:
        decoded = base64.urlsafe_b64decode(value.encode())
    except Exception:
        return False
    return len(decoded) == 32


def validate_production_settings(service_name: str, *, require_ai_encryption: bool = False) -> None:
    """Fail fast on settings that must never reach production."""
    if not is_production():
        return

    errors: list[str] = []
    jwt_secret = os.getenv("JWT_SECRET", "")
    db_pass = os.getenv("DB_PASS", "")
    auth_required = os.getenv("AUTH_REQUIRED", "true").lower()

    if is_placeholder(jwt_secret) or len(jwt_secret) < 32:
        errors.append("JWT_SECRET must be set to a non-default value of at least 32 characters")
    if auth_required == "false":
        errors.append("AUTH_REQUIRED=false is forbidden in production")
    if is_placeholder(db_pass):
        errors.append("DB_PASS must be set to a non-placeholder production password")
    if os.getenv("USE_SQLITE", "").lower() == "true":
        errors.append("USE_SQLITE=true is forbidden in production")
    if os.getenv("DB_HOST", "postgres") in {"", "localhost", "127.0.0.1"}:
        errors.append("DB_HOST must point to the production database service")
    if require_ai_encryption:
        ai_key = os.getenv("AI_ENCRYPTION_KEY", "").strip()
        if is_placeholder(ai_key):
            errors.append("AI_ENCRYPTION_KEY must be configured before storing AI API keys")
        elif not looks_like_fernet_key(ai_key):
            errors.append("AI_ENCRYPTION_KEY must be a valid Fernet key")

    if errors:
        detail = "; ".join(errors)
        raise RuntimeError(f"{service_name} refused to start with unsafe production settings: {detail}")


def fastapi_docs_kwargs() -> dict:
    if is_production():
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {
        "docs_url": "/api/v1/docs",
        "redoc_url": "/api/v1/redoc",
        "openapi_url": "/api/v1/openapi.json",
    }
