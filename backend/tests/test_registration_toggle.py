from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from backend.services.user_service.app.api.v1 import auth


class RegistrationToggleTests(unittest.TestCase):
    def test_registration_disabled_returns_403_before_rate_limit(self) -> None:
        with patch.dict("os.environ", {"REGISTRATION_ENABLED": "false"}, clear=False):
            with patch.object(auth, "enforce_rate_limit", new=AsyncMock()) as limiter:
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(auth.register(SimpleNamespace(), SimpleNamespace(), object()))

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail, "registration is disabled")
        limiter.assert_not_called()

    def test_registration_enabled_accepts_common_truthy_values(self) -> None:
        for value in ("1", "true", "yes", "on"):
            with self.subTest(value=value):
                with patch.dict("os.environ", {"REGISTRATION_ENABLED": value}, clear=False):
                    self.assertTrue(auth._registration_enabled())

    def test_registration_disabled_for_other_values(self) -> None:
        for value in ("0", "false", "no", "off", ""):
            with self.subTest(value=value):
                with patch.dict("os.environ", {"REGISTRATION_ENABLED": value}, clear=False):
                    self.assertFalse(auth._registration_enabled())


if __name__ == "__main__":
    unittest.main()
