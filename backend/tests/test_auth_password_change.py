from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from backend.services.user_service.app.api.v1 import auth
from backend.shared.schemas import UserPasswordChange
from backend.shared.security import hash_password, verify_password


class _Query:
    def __init__(self, user):
        self.user = user

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.user


class _Db:
    def __init__(self, user):
        self.user = user
        self.added = []
        self.commits = 0

    def query(self, _model):
        return _Query(self.user)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.commits += 1


class PasswordChangeTests(unittest.IsolatedAsyncioTestCase):
    def _request(self):
        return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))

    def _user(self):
        return SimpleNamespace(
            id=7,
            username="unit",
            is_active=True,
            password_hash=hash_password("OldPass123"),
        )

    async def test_change_password_updates_hash_and_audits(self) -> None:
        user = self._user()
        db = _Db(user)
        data = UserPasswordChange(current_password="OldPass123", new_password="NewPass456")

        with patch.object(auth, "enforce_rate_limit", new=AsyncMock()):
            result = await auth.change_password(data, self._request(), user, db)

        self.assertEqual(result, {"message": "密码已修改"})
        self.assertTrue(verify_password("NewPass456", user.password_hash))
        self.assertFalse(verify_password("OldPass123", user.password_hash))
        self.assertEqual(db.commits, 1)
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].action, "auth.password_changed")

    async def test_change_password_rejects_wrong_current_password(self) -> None:
        user = self._user()
        original_hash = user.password_hash
        db = _Db(user)
        data = UserPasswordChange(current_password="WrongPass123", new_password="NewPass456")

        with patch.object(auth, "enforce_rate_limit", new=AsyncMock()):
            with self.assertRaises(HTTPException) as raised:
                await auth.change_password(data, self._request(), user, db)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("当前密码不正确", raised.exception.detail)
        self.assertEqual(user.password_hash, original_hash)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.added[0].action, "auth.password_change_failed")

    async def test_change_password_rejects_weak_new_password(self) -> None:
        user = self._user()
        original_hash = user.password_hash
        db = _Db(user)
        data = UserPasswordChange(current_password="OldPass123", new_password="lowercase")

        with patch.object(auth, "enforce_rate_limit", new=AsyncMock()):
            with self.assertRaises(HTTPException) as raised:
                await auth.change_password(data, self._request(), user, db)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("大写字母", raised.exception.detail)
        self.assertEqual(user.password_hash, original_hash)
        self.assertEqual(db.commits, 0)

    async def test_change_password_rejects_same_password(self) -> None:
        user = self._user()
        original_hash = user.password_hash
        db = _Db(user)
        data = UserPasswordChange(current_password="OldPass123", new_password="OldPass123")

        with patch.object(auth, "enforce_rate_limit", new=AsyncMock()):
            with self.assertRaises(HTTPException) as raised:
                await auth.change_password(data, self._request(), user, db)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("不能和当前密码相同", raised.exception.detail)
        self.assertEqual(user.password_hash, original_hash)
        self.assertEqual(db.commits, 0)


if __name__ == "__main__":
    unittest.main()
