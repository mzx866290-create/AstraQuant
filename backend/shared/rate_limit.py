"""Small fixed-window rate limiter shared by FastAPI services."""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status

from backend.shared.cache import get_cache_manager
from backend.shared.config import is_production

logger = logging.getLogger(__name__)

_memory_windows: dict[str, tuple[int, float]] = {}


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    key: str
    count: int
    limit: int
    retry_after: int


def client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def user_identity(user: Any) -> str:
    user_id = getattr(user, "id", None)
    return f"user:{user_id}" if user_id is not None else "user:unknown"


def _safe_identity(identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return digest


def _window(now: float, window_seconds: int) -> tuple[int, int]:
    window_start = int(now // window_seconds) * window_seconds
    retry_after = max(window_start + window_seconds - int(now), 1)
    return window_start, retry_after


def reset_rate_limit_state() -> None:
    _memory_windows.clear()


async def _increment_memory(key: str, window_seconds: int, now: float) -> int:
    count, expires_at = _memory_windows.get(key, (0, now + window_seconds))
    if now >= expires_at:
        count = 0
        expires_at = now + window_seconds
    count += 1
    _memory_windows[key] = (count, expires_at)
    return count


async def _increment_redis(redis, key: str, window_seconds: int) -> int:
    count = await redis.incr(key)
    if int(count) == 1:
        await redis.expire(key, window_seconds)
    return int(count)


async def check_rate_limit(
    *,
    scope: str,
    identity: str,
    limit: int,
    window_seconds: int,
    fail_closed: bool = False,
) -> RateLimitResult:
    if limit <= 0 or window_seconds <= 0:
        raise ValueError("rate limit and window_seconds must be positive")

    now = time.time()
    window_start, retry_after = _window(now, window_seconds)
    key = f"stock:rl:{scope}:{_safe_identity(identity)}:{window_start}"

    try:
        cache = await get_cache_manager()
        redis = cache.redis
    except Exception as exc:
        redis = None
        logger.warning("rate limiter cache unavailable for %s: %s", scope, exc)

    if redis is None and is_production():
        if fail_closed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="rate limiter is unavailable",
                headers={"Retry-After": str(retry_after)},
            )
        logger.warning("rate limiter running fail-open for %s because Redis is unavailable", scope)
        return RateLimitResult(True, key, 0, limit, retry_after)

    count = await _increment_redis(redis, key, window_seconds) if redis is not None else await _increment_memory(key, window_seconds, now)
    return RateLimitResult(count <= limit, key, count, limit, retry_after)


async def enforce_rate_limit(
    *,
    scope: str,
    identity: str,
    limit: int,
    window_seconds: int,
    fail_closed: bool = False,
) -> RateLimitResult:
    result = await check_rate_limit(
        scope=scope,
        identity=identity,
        limit=limit,
        window_seconds=window_seconds,
        fail_closed=fail_closed,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded for {scope}",
            headers={"Retry-After": str(result.retry_after)},
        )
    return result
