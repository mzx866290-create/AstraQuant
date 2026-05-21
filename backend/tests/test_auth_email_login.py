from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.services.user_service.app.api.v1.auth import login
from backend.shared.models import Base, User
from backend.shared.schemas import UserLogin
from backend.shared.security import decode_access_token, hash_password


class AuthEmailLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

    def test_login_accepts_registered_email(self) -> None:
        db = self.Session()
        try:
            db.add(User(
                username="mzx5146",
                email="383381391@qq.com",
                password_hash=hash_password("6216835Mo"),
                role="free",
                is_active=True,
            ))
            db.commit()
            request = SimpleNamespace(
                client=SimpleNamespace(host="127.0.0.1"),
                headers={},
            )

            with patch("backend.shared.security.JWT_SECRET", "unit-test-secret"), patch(
                "backend.services.user_service.app.api.v1.auth.enforce_rate_limit",
                new=AsyncMock(),
            ), patch("backend.services.user_service.app.api.v1.auth.audit_log"):
                response = asyncio.run(login(
                    UserLogin(username="383381391@qq.com", password="6216835Mo"),
                    request,
                    db,
                ))
                payload = decode_access_token(response.access_token)

                self.assertEqual(payload["username"], "mzx5146")
                self.assertEqual(payload["role"], "free")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
