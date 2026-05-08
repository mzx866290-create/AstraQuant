"""Minimal audit logging helpers for security-sensitive actions."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from .models import User, UserActivityLog

logger = logging.getLogger(__name__)


def client_ip(request: Request | None) -> str | None:
    if not request:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:45]
    return request.client.host[:45] if request.client else None


def user_agent(request: Request | None) -> str | None:
    if not request:
        return None
    value = request.headers.get("user-agent")
    return value[:1000] if value else None


def audit_log(
    db: Session,
    *,
    action: str,
    actor: User | None = None,
    request: Request | None = None,
    target: str | None = None,
    user_id: int | None = None,
) -> None:
    """Append an audit log row without taking ownership of transaction commit."""
    try:
        resolved_user_id = user_id if user_id is not None else (actor.id if actor else None)
        if resolved_user_id is None:
            logger.info("anonymous audit action=%s target=%s ip=%s", action, target, client_ip(request))
            return
        db.add(UserActivityLog(
            user_id=resolved_user_id,
            action=action[:50],
            target=target[:100] if target else None,
            ip_address=client_ip(request),
            user_agent=user_agent(request),
        ))
    except Exception as exc:
        logger.warning("audit log write failed for action=%s target=%s: %s", action, target, exc)
