from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.services.user_service.app.api.v1 import auth
from backend.shared.models import Base, PasswordResetToken, User
from backend.shared.schemas import PasswordResetConfirm, PasswordResetRequest
from backend.shared.security import hash_password, verify_password


class AuthPasswordResetTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

    def _request(self):
        return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))

    def _create_user(self, db):
        user = User(
            username="13560680486",
            email="514533993@qq.com",
            password_hash=hash_password("OldPass123"),
            role="premium",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def test_request_and_confirm_password_reset(self) -> None:
        db = self.Session()
        try:
            user = self._create_user(db)
            sent_tokens: list[str] = []

            def _capture_email(**kwargs):
                sent_tokens.append(kwargs["token"])

            with patch.object(auth, "enforce_rate_limit", new=AsyncMock()), patch.object(
                auth, "password_reset_email_configured", return_value=True
            ), patch.object(auth, "send_password_reset_email", side_effect=_capture_email):
                response = asyncio.run(auth.request_password_reset(
                    PasswordResetRequest(identifier="13560680486"),
                    self._request(),
                    db,
                ))

            self.assertEqual(response.message, auth.PASSWORD_RESET_GENERIC_MESSAGE)
            self.assertEqual(len(sent_tokens), 1)

            token_row = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).first()
            self.assertIsNotNone(token_row)
            self.assertNotEqual(token_row.token_hash, sent_tokens[0])
            self.assertIsNone(token_row.used_at)

            with patch.object(auth, "enforce_rate_limit", new=AsyncMock()):
                reset_response = asyncio.run(auth.reset_password(
                    PasswordResetConfirm(token=sent_tokens[0], new_password="NewPass456"),
                    self._request(),
                    db,
                ))

            db.refresh(user)
            db.refresh(token_row)
            self.assertEqual(reset_response.message, "Password has been reset")
            self.assertTrue(verify_password("NewPass456", user.password_hash))
            self.assertFalse(verify_password("OldPass123", user.password_hash))
            self.assertIsNotNone(token_row.used_at)
        finally:
            db.close()

    def test_request_requires_email_configuration(self) -> None:
        db = self.Session()
        try:
            self._create_user(db)

            with patch.object(auth, "enforce_rate_limit", new=AsyncMock()), patch.object(
                auth, "password_reset_email_configured", return_value=False
            ):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(auth.request_password_reset(
                        PasswordResetRequest(identifier="13560680486"),
                        self._request(),
                        db,
                    ))

            self.assertEqual(raised.exception.status_code, 503)
            self.assertEqual(db.query(PasswordResetToken).count(), 0)
        finally:
            db.close()

    def test_reset_rejects_reused_token(self) -> None:
        db = self.Session()
        try:
            user = self._create_user(db)
            raw_token = "x" * 40
            db.add(PasswordResetToken(
                user_id=user.id,
                token_hash=auth._token_hash(raw_token),
                expires_at=auth._utcnow() + auth.timedelta(minutes=10),
                used_at=auth._utcnow(),
            ))
            db.commit()

            with patch.object(auth, "enforce_rate_limit", new=AsyncMock()):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(auth.reset_password(
                        PasswordResetConfirm(token=raw_token, new_password="NewPass456"),
                        self._request(),
                        db,
                    ))

            self.assertEqual(raised.exception.status_code, 400)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
