"""Email helpers for account recovery flows."""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def password_reset_email_configured() -> bool:
    return all(
        os.getenv(name, "").strip()
        for name in ("SMTP_HOST", "SMTP_FROM", "PUBLIC_APP_URL")
    )


def _smtp_port() -> int:
    try:
        return int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        return 587


def _smtp_use_tls() -> bool:
    return os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}


def _smtp_use_ssl() -> bool:
    configured = os.getenv("SMTP_USE_SSL", "").strip().lower()
    if configured:
        return configured in {"1", "true", "yes", "on"}
    return _smtp_port() == 465


def build_password_reset_url(token: str) -> str:
    app_url = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")
    return f"{app_url}/reset-password?token={token}"


def send_password_reset_email(*, to_email: str, username: str, token: str, expires_minutes: int) -> None:
    if not password_reset_email_configured():
        raise RuntimeError("password reset email is not configured")

    host = os.getenv("SMTP_HOST", "").strip()
    port = _smtp_port()
    username_env = os.getenv("SMTP_USER", "").strip()
    password_env = os.getenv("SMTP_PASSWORD", "")
    from_email = os.getenv("SMTP_FROM", "").strip()
    from_name = os.getenv("SMTP_FROM_NAME", "Stock Platform").strip() or "Stock Platform"
    reset_url = build_password_reset_url(token)

    message = EmailMessage()
    message["Subject"] = "Password reset request"
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = to_email
    message.set_content(
        "\n".join(
            [
                f"Hello {username},",
                "",
                "We received a request to reset your password.",
                f"Open this link within {expires_minutes} minutes:",
                reset_url,
                "",
                "If you did not request this, you can ignore this email.",
            ]
        )
    )

    smtp_cls = smtplib.SMTP_SSL if _smtp_use_ssl() else smtplib.SMTP
    with smtp_cls(host, port, timeout=15) as smtp:
        if not _smtp_use_ssl() and _smtp_use_tls():
            smtp.starttls()
        if username_env or password_env:
            smtp.login(username_env, password_env)
        smtp.send_message(message)
    logger.info("password reset email sent to %s", to_email)
