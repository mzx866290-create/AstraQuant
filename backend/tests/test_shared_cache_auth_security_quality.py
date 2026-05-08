from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend.shared import auth, cache, security


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.deleted: list[str] = []
        self.scan_batches = [(1, ["stock:quote:600519", "stock:quote:000001"]), (0, [])]

    async def get(self, key: str):
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, payload: str) -> None:
        self.values[key] = payload
        self.ttls[key] = ttl

    async def delete(self, *keys: str) -> None:
        self.deleted.extend(keys)
        for key in keys:
            self.values.pop(key, None)

    async def scan(self, cursor: int, match: str):
        return self.scan_batches.pop(0)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True


class CacheManagerBehaviorTests(unittest.TestCase):
    def test_memory_cache_get_set_invalidate_and_pattern_invalidation(self) -> None:
        store: dict = {}
        manager = cache.CacheManager(client=None)
        manager._memory = store

        asyncio.run(manager.set("quote", "600519", value={"price": 10}, ttl=timedelta(seconds=60)))
        self.assertEqual(asyncio.run(manager.get("quote", "600519")), {"price": 10})

        store["stock:quote:expired"] = {"value": "old", "expires": 0}
        self.assertIsNone(asyncio.run(manager.get("quote", "expired")))
        self.assertNotIn("stock:quote:expired", store)

        asyncio.run(manager.invalidate("quote", "600519"))
        self.assertIsNone(asyncio.run(manager.get("quote", "600519")))

        asyncio.run(manager.set("daily_kline", "600519", value=[1], ttl=timedelta(seconds=60)))
        asyncio.run(manager.set("daily_kline", "000001", value=[2], ttl=timedelta(seconds=60)))
        asyncio.run(manager.invalidate_pattern("daily_kline:*"))
        self.assertEqual(store, {})

    def test_redis_cache_roundtrip_and_pattern_delete_use_json_payloads(self) -> None:
        redis = _FakeRedis()
        manager = cache.CacheManager(client=redis)

        asyncio.run(manager.set("search_result", "maotai", value={"items": [1]}))
        self.assertEqual(redis.ttls["stock:search_result:maotai"], 300)
        self.assertEqual(json.loads(redis.values["stock:search_result:maotai"]), {"items": [1]})
        self.assertEqual(asyncio.run(manager.get("search_result", "maotai")), {"items": [1]})

        asyncio.run(manager.invalidate("search_result", "maotai"))
        self.assertIn("stock:search_result:maotai", redis.deleted)

        asyncio.run(manager.invalidate_pattern("stock:quote:*"))
        self.assertIn("stock:quote:600519", redis.deleted)
        self.assertIn("stock:quote:000001", redis.deleted)

    def test_cached_decorator_short_circuits_cache_hits_and_stores_misses(self) -> None:
        class _Cache:
            def __init__(self, hit=None) -> None:
                self.hit = hit
                self.get_calls = []
                self.set_calls = []

            async def get(self, category, *args):
                self.get_calls.append((category, args))
                return self.hit

            async def set(self, category, *args, value):
                self.set_calls.append((category, args, value))

        class _Service:
            def __init__(self, cached_value=None) -> None:
                self.cache = _Cache(cached_value)
                self.calls = 0

            @cache.cached("unit")
            async def load(self, symbol: str, *, period: str):
                self.calls += 1
                return {"symbol": symbol, "period": period}

        hit_service = _Service(cached_value={"cached": True})
        self.assertEqual(asyncio.run(hit_service.load("600519", period="1d")), {"cached": True})
        self.assertEqual(hit_service.calls, 0)
        self.assertEqual(hit_service.cache.set_calls, [])

        miss_service = _Service()
        self.assertEqual(asyncio.run(miss_service.load("600519", period="1d")), {"symbol": "600519", "period": "1d"})
        self.assertEqual(miss_service.calls, 1)
        self.assertEqual(miss_service.cache.set_calls[0][0], "unit")

    def test_init_and_close_redis_handle_success_and_failure_paths(self) -> None:
        fake_redis = _FakeRedis()
        redis_module = SimpleNamespace(from_url=AsyncMock(return_value=fake_redis))
        redis_parent = SimpleNamespace(asyncio=redis_module)

        with patch.dict("sys.modules", {"redis": redis_parent, "redis.asyncio": redis_module}):
            with patch.dict("os.environ", {"REDIS_HOST": "redis.local", "REDIS_PORT": "6380"}, clear=False):
                cache.redis_client = None
                cache._redis_unavailable = False
                asyncio.run(cache.init_redis())

        self.assertIs(cache.redis_client, fake_redis)
        redis_module.from_url.assert_awaited_once()
        asyncio.run(cache.close_redis())
        self.assertIsNone(cache.redis_client)
        self.assertTrue(fake_redis.closed)

        cache.redis_client = None
        cache._redis_unavailable = False
        original_import = __import__

        def fail_redis_import(name, *args, **kwargs):
            if name.startswith("redis"):
                raise ImportError("redis missing")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_redis_import):
            asyncio.run(cache.init_redis())
        self.assertTrue(cache._redis_unavailable)
        self.assertIsNone(cache.redis_client)
        cache._redis_unavailable = False


class AuthBehaviorTests(unittest.TestCase):
    def test_token_extraction_accepts_credentials_or_bearer_header_only(self) -> None:
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="abc")

        self.assertEqual(auth.get_token_from_auth(credentials=credentials), "abc")
        self.assertEqual(auth.get_token_from_auth(auth_header="Bearer xyz"), "xyz")
        self.assertIsNone(auth.get_token_from_auth(auth_header="Basic xyz"))
        self.assertIsNone(auth.get_token_from_auth(auth_header="Bearer"))

    def test_require_role_allows_matching_roles_and_blocks_dev_admin_without_override(self) -> None:
        checker = auth.require_role("admin")

        admin = SimpleNamespace(role="admin")
        with patch.object(auth, "AUTH_REQUIRED", True):
            self.assertIs(asyncio.run(checker(admin)), admin)

        with patch.object(auth, "AUTH_REQUIRED", True):
            with self.assertRaises(HTTPException) as wrong_role:
                asyncio.run(checker(SimpleNamespace(role="free")))
        self.assertEqual(wrong_role.exception.status_code, 403)

        with patch.object(auth, "AUTH_REQUIRED", False), patch.object(auth, "_allow_dev_admin", return_value=False):
            with self.assertRaises(HTTPException) as dev_admin:
                asyncio.run(checker(admin))
        self.assertEqual(dev_admin.exception.status_code, 403)
        self.assertIn("ALLOW_DEV_ADMIN", dev_admin.exception.detail)

    def test_get_current_user_optional_returns_none_for_invalid_payloads_and_closed_session(self) -> None:
        session = SimpleNamespace(close=Mock())
        with patch.object(auth, "AUTH_REQUIRED", True), patch.object(auth, "decode_access_token", return_value={"sub": "bad"}):
            result = asyncio.run(auth.get_current_user_optional(HTTPAuthorizationCredentials(scheme="Bearer", credentials="t")))
        self.assertIsNone(result)

        with patch.object(auth, "AUTH_REQUIRED", True), patch.object(auth, "decode_access_token", return_value={"sub": "42"}):
            with patch.object(auth, "SessionLocal", return_value=_AuthSession(user=None, close=session.close)):
                result = asyncio.run(auth.get_current_user_optional(HTTPAuthorizationCredentials(scheme="Bearer", credentials="t")))
        self.assertIsNone(result)
        session.close.assert_called_once()

    def test_quota_availability_resets_stale_windows_and_reports_exhaustion(self) -> None:
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        quota = SimpleNamespace(
            daily_used=3,
            daily_limit=5,
            monthly_used=7,
            monthly_limit=10,
            last_reset_daily=yesterday.replace(tzinfo=None),
            last_reset_monthly=yesterday.replace(day=1, tzinfo=None),
        )

        with patch.object(auth, "get_user_quota", return_value=quota):
            available, message = auth.check_quota_available(1)

        self.assertTrue(available)
        self.assertEqual(message, "")
        self.assertEqual(quota.daily_used, 0)

        quota.daily_used = quota.daily_limit
        quota.last_reset_daily = datetime.now(timezone.utc)
        quota.last_reset_monthly = datetime.now(timezone.utc)
        with patch.object(auth, "get_user_quota", return_value=quota):
            available, message = auth.check_quota_available(1)
        self.assertFalse(available)
        self.assertIn("daily quota exhausted", message)

        quota.daily_used = 0
        quota.monthly_used = quota.monthly_limit
        with patch.object(auth, "get_user_quota", return_value=quota):
            available, message = auth.check_quota_available(1)
        self.assertFalse(available)
        self.assertIn("monthly quota exhausted", message)

    def test_increment_quota_commits_when_quota_exists_and_closes_session(self) -> None:
        quota = SimpleNamespace(daily_used=1, monthly_used=2, last_reset_daily=None, last_reset_monthly=None)
        session = _AuthSession(quota=quota)

        with patch.object(auth, "SessionLocal", return_value=session):
            auth.increment_quota(7)

        self.assertEqual(quota.daily_used, 2)
        self.assertEqual(quota.monthly_used, 3)
        self.assertIsNotNone(quota.last_reset_daily)
        self.assertEqual(session.commits, 1)
        self.assertTrue(session.closed)

    def test_ai_key_encryption_roundtrip_and_plaintext_fallback_boundaries(self) -> None:
        from cryptography.fernet import Fernet

        explicit_key = Fernet.generate_key().decode()
        with patch.dict("os.environ", {"AI_ENCRYPTION_KEY": explicit_key}, clear=False), patch.object(
            auth, "is_production", return_value=False
        ):
            encrypted = auth.encrypt_api_key("sk-unit")
            self.assertNotEqual(encrypted, "sk-unit")
            self.assertEqual(auth.decrypt_api_key(encrypted), "sk-unit")

        with patch.dict("os.environ", {"AI_ENCRYPTION_KEY": ""}, clear=False), patch.object(
            auth, "is_production", return_value=False
        ):
            self.assertEqual(auth.decrypt_api_key("legacy-plaintext"), "legacy-plaintext")

        with patch.dict("os.environ", {"AI_ENCRYPTION_KEY": "bad-key"}, clear=False), patch.object(
            auth, "is_production", return_value=False
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid"):
                auth.encrypt_api_key("sk-unit")


class SecurityBehaviorTests(unittest.TestCase):
    def test_password_hashing_truncates_after_bcrypt_72_byte_boundary(self) -> None:
        base = "a" * 72
        hashed = security.hash_password(base + "first-tail")

        self.assertTrue(security.verify_password(base + "second-tail", hashed))
        self.assertFalse(security.verify_password("b" + base[1:], hashed))

    def test_access_token_roundtrip_and_invalid_token_handling(self) -> None:
        with patch.object(security, "JWT_SECRET", "unit-secret-with-enough-length"):
            token = security.create_access_token({"sub": "42", "role": "admin"}, expires_delta=timedelta(minutes=5))
            payload = security.decode_access_token(token)
            self.assertEqual(payload["sub"], "42")
            self.assertEqual(payload["role"], "admin")
            self.assertIsNone(security.decode_access_token(token + "broken"))

    def test_jwt_secret_requires_value_and_blocks_placeholder_in_production(self) -> None:
        with patch.object(security, "JWT_SECRET", ""):
            with self.assertRaisesRegex(RuntimeError, "JWT_SECRET is required"):
                security._jwt_secret()

        with patch.object(security, "JWT_SECRET", "change-me"), patch.object(
            security, "is_production", return_value=True
        ), patch.object(security, "is_placeholder", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "unsafe default"):
                security._jwt_secret()

    def test_get_token_from_header_accepts_case_insensitive_bearer_only(self) -> None:
        self.assertEqual(security.get_token_from_header("bearer abc"), "abc")
        self.assertEqual(security.get_token_from_header("Bearer abc"), "abc")
        self.assertIsNone(security.get_token_from_header(""))
        self.assertIsNone(security.get_token_from_header("Basic abc"))
        self.assertIsNone(security.get_token_from_header("Bearer"))


class _AuthSession:
    def __init__(self, *, user=None, quota=None, close=None) -> None:
        self.user = user
        self.quota = quota
        self.close_mock = close
        self.commits = 0
        self.closed = False

    def query(self, model):
        return _AuthQuery(self)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True
        if self.close_mock:
            self.close_mock()


class _AuthQuery:
    def __init__(self, session: _AuthSession) -> None:
        self.session = session

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.session.quota if self.session.quota is not None else self.session.user


if __name__ == "__main__":
    unittest.main()
