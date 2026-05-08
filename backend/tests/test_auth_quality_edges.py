from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend.shared import auth


def _bearer(token: str = "unit-token") -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


class AuthCurrentUserEdgeTests(unittest.TestCase):
    def test_get_current_user_rejects_missing_token_before_db(self) -> None:
        with patch.object(auth, "AUTH_REQUIRED", True), patch.object(auth, "SessionLocal") as session_local:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(auth.get_current_user(None))

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail, "missing bearer token")
        session_local.assert_not_called()

    def test_get_current_user_rejects_payload_without_subject(self) -> None:
        with patch.object(auth, "AUTH_REQUIRED", True), patch.object(auth, "decode_access_token", return_value={"role": "free"}):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(auth.get_current_user(_bearer()))

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail, "invalid token payload")

    def test_get_current_user_rejects_non_int_subject(self) -> None:
        with patch.object(auth, "AUTH_REQUIRED", True), patch.object(auth, "decode_access_token", return_value={"sub": "not-int"}):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(auth.get_current_user(_bearer()))

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail, "invalid token payload")

    def test_get_current_user_rejects_missing_user_and_closes_session(self) -> None:
        session = _AuthSession(user=None)

        with patch.object(auth, "AUTH_REQUIRED", True), patch.object(auth, "decode_access_token", return_value={"sub": "42"}):
            with patch.object(auth, "SessionLocal", return_value=session):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(auth.get_current_user(_bearer()))

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail, "user not found")
        self.assertTrue(session.closed)

    def test_get_current_user_rejects_inactive_user_and_closes_session(self) -> None:
        session = _AuthSession(user=SimpleNamespace(id=42, is_active=False, role="free"))

        with patch.object(auth, "AUTH_REQUIRED", True), patch.object(auth, "decode_access_token", return_value={"sub": "42"}):
            with patch.object(auth, "SessionLocal", return_value=session):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(auth.get_current_user(_bearer()))

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail, "user is disabled")
        self.assertTrue(session.closed)

    def test_get_current_user_returns_active_user_and_closes_session(self) -> None:
        user = SimpleNamespace(id=42, is_active=True, role="premium")
        session = _AuthSession(user=user)

        with patch.object(auth, "AUTH_REQUIRED", True), patch.object(auth, "decode_access_token", return_value={"sub": "42"}):
            with patch.object(auth, "SessionLocal", return_value=session):
                result = asyncio.run(auth.get_current_user(_bearer()))

        self.assertIs(result, user)
        self.assertTrue(session.closed)

    def test_get_current_user_forbids_disabled_auth_in_production(self) -> None:
        with patch.object(auth, "AUTH_REQUIRED", False), patch.object(auth, "is_production", return_value=True):
            with patch.object(auth, "_get_or_create_dev_user") as dev_user:
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(auth.get_current_user(None))

        self.assertEqual(raised.exception.status_code, 500)
        self.assertIn("forbids disabling authentication", raised.exception.detail)
        dev_user.assert_not_called()


class AuthOptionalUserEdgeTests(unittest.TestCase):
    def test_optional_user_returns_none_when_auth_disabled_in_production(self) -> None:
        with patch.object(auth, "AUTH_REQUIRED", False), patch.object(auth, "is_production", return_value=True):
            with patch.object(auth, "_get_or_create_dev_user") as dev_user:
                result = asyncio.run(auth.get_current_user_optional(None))

        self.assertIsNone(result)
        dev_user.assert_not_called()

    def test_optional_user_returns_dev_user_when_auth_disabled_outside_production(self) -> None:
        user = SimpleNamespace(id=1, username="dev", role="free")

        with patch.object(auth, "AUTH_REQUIRED", False), patch.object(auth, "is_production", return_value=False):
            with patch.object(auth, "_get_or_create_dev_user", return_value=user) as dev_user:
                result = asyncio.run(auth.get_current_user_optional(None))

        self.assertIs(result, user)
        dev_user.assert_called_once_with()


class UserQuotaEdgeTests(unittest.TestCase):
    def test_get_user_quota_raises_404_when_user_missing(self) -> None:
        session = _AuthSession(user=None, quota=None)

        with patch.object(auth, "SessionLocal", return_value=session):
            with self.assertRaises(HTTPException) as raised:
                auth.get_user_quota(404)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "user not found")
        self.assertEqual(session.added, [])
        self.assertEqual(session.commits, 0)
        self.assertTrue(session.closed)

    def test_get_user_quota_creates_role_specific_limits(self) -> None:
        expected_limits = {
            "free": (10, 100),
            "premium": (50, 500),
            "admin": (1000, 10000),
            None: (10, 100),
        }

        for role, (daily_limit, monthly_limit) in expected_limits.items():
            with self.subTest(role=role):
                session = _AuthSession(user=SimpleNamespace(id=7, role=role), quota=None)

                with patch.object(auth, "SessionLocal", return_value=session):
                    quota = auth.get_user_quota(7)

                self.assertIs(quota, session.added[0])
                self.assertEqual(quota.user_id, 7)
                self.assertEqual(quota.daily_limit, daily_limit)
                self.assertEqual(quota.monthly_limit, monthly_limit)
                self.assertEqual(session.commits, 1)
                self.assertEqual(session.refreshes, [quota])
                self.assertTrue(session.closed)

    def test_get_user_quota_returns_existing_quota_without_writes(self) -> None:
        quota = SimpleNamespace(user_id=9, daily_limit=123, monthly_limit=456)
        session = _AuthSession(user=SimpleNamespace(id=9, role="admin"), quota=quota)

        with patch.object(auth, "SessionLocal", return_value=session):
            result = auth.get_user_quota(9)

        self.assertIs(result, quota)
        self.assertEqual(session.added, [])
        self.assertEqual(session.commits, 0)
        self.assertEqual(session.refreshes, [])
        self.assertTrue(session.closed)


class AIKeyEdgeTests(unittest.TestCase):
    def test_get_ai_fernet_requires_explicit_key_for_production_storage(self) -> None:
        with patch.dict("os.environ", {"AI_ENCRYPTION_KEY": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "AI_ENCRYPTION_KEY is required"):
                auth._get_ai_fernet(require_explicit_key=True)

    def test_get_ai_fernet_rejects_invalid_explicit_key(self) -> None:
        with patch.dict("os.environ", {"AI_ENCRYPTION_KEY": "not-a-fernet-key"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "AI_ENCRYPTION_KEY is invalid"):
                auth._get_ai_fernet(require_explicit_key=False)

    def test_get_ai_fernet_logs_derived_key_warning_once(self) -> None:
        env = {
            "AI_ENCRYPTION_KEY": "",
            "JWT_SECRET": "unit-dev-secret-with-enough-length",
            "APP_ENV": "development",
        }

        with patch.dict("os.environ", env, clear=False), patch.object(auth, "_warned_derived_api_key_storage", False):
            with self.assertLogs(auth.logger, level="WARNING") as logs:
                first = auth._get_ai_fernet(require_explicit_key=False)
                second = auth._get_ai_fernet(require_explicit_key=False)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        derived_warnings = [
            message for message in logs.output if "AI_ENCRYPTION_KEY is not set; deriving" in message
        ]
        self.assertEqual(len(derived_warnings), 1)

    def test_decrypt_api_key_rejects_bad_ciphertext_in_production(self) -> None:
        with patch.dict("os.environ", {"AI_ENCRYPTION_KEY": Fernet.generate_key().decode()}, clear=False):
            with patch.object(auth, "is_production", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "before reading AI API keys in production"):
                    auth.decrypt_api_key("not-fernet-ciphertext")

    def test_decrypt_api_key_rejects_ciphertext_from_different_explicit_key(self) -> None:
        original_key = Fernet.generate_key()
        wrong_key = Fernet.generate_key().decode()
        encrypted = Fernet(original_key).encrypt(b"sk-unit").decode()

        with patch.dict("os.environ", {"AI_ENCRYPTION_KEY": wrong_key}, clear=False):
            with patch.object(auth, "is_production", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "could not be decrypted"):
                    auth.decrypt_api_key(encrypted)


class _AuthSession:
    def __init__(self, *, user=None, quota=None) -> None:
        self.user = user
        self.quota = quota
        self.added = []
        self.refreshes = []
        self.commits = 0
        self.closed = False
        self.close_mock = Mock()

    def query(self, model):
        return _AuthQuery(self, model)

    def add(self, item) -> None:
        self.added.append(item)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, item) -> None:
        self.refreshes.append(item)

    def close(self) -> None:
        self.closed = True
        self.close_mock()


class _AuthQuery:
    def __init__(self, session: _AuthSession, model) -> None:
        self.session = session
        self.model = model

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        if self.model is auth.UserQuota:
            return self.session.quota
        if self.model is auth.User:
            return self.session.user
        raise AssertionError(f"unexpected model query: {self.model!r}")


if __name__ == "__main__":
    unittest.main()
