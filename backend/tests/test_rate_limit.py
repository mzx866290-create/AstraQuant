from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException


class _FakeCache:
    def __init__(self, redis=None):
        self.redis = redis


class _FakeRedis:
    def __init__(self):
        self.counts: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.expirations[key] = ttl


class _FailingRedis:
    async def incr(self, key: str) -> int:
        raise RuntimeError("redis closed")


class RateLimitUnitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from backend.shared.rate_limit import reset_rate_limit_state

        reset_rate_limit_state()

    async def test_memory_fallback_blocks_after_limit_in_development(self) -> None:
        from backend.shared.rate_limit import enforce_rate_limit

        async def fake_cache():
            return _FakeCache(redis=None)

        with patch.dict("os.environ", {"APP_ENV": "development"}, clear=True):
            with patch("backend.shared.rate_limit.get_cache_manager", fake_cache):
                await enforce_rate_limit(scope="unit:test", identity="ip:1", limit=2, window_seconds=60)
                await enforce_rate_limit(scope="unit:test", identity="ip:1", limit=2, window_seconds=60)
                with self.assertRaises(HTTPException) as ctx:
                    await enforce_rate_limit(scope="unit:test", identity="ip:1", limit=2, window_seconds=60)

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("Retry-After", ctx.exception.headers)

    async def test_redis_counter_uses_incr_and_expire(self) -> None:
        from backend.shared.rate_limit import check_rate_limit

        redis = _FakeRedis()

        async def fake_cache():
            return _FakeCache(redis=redis)

        with patch("backend.shared.rate_limit.get_cache_manager", fake_cache):
            result = await check_rate_limit(scope="unit:redis", identity="user:1", limit=3, window_seconds=30)

        self.assertTrue(result.allowed)
        self.assertEqual(result.count, 1)
        self.assertEqual(list(redis.counts.values()), [1])
        self.assertEqual(list(redis.expirations.values()), [30])

    async def test_production_fail_closed_when_redis_is_unavailable(self) -> None:
        from backend.shared.rate_limit import check_rate_limit

        async def fake_cache():
            return _FakeCache(redis=None)

        with patch.dict("os.environ", {"APP_ENV": "production"}, clear=True):
            with patch("backend.shared.rate_limit.get_cache_manager", fake_cache):
                with self.assertRaises(HTTPException) as ctx:
                    await check_rate_limit(
                        scope="auth:login:ip",
                        identity="ip:1",
                        limit=5,
                        window_seconds=60,
                        fail_closed=True,
                    )

        self.assertEqual(ctx.exception.status_code, 503)

    async def test_production_fail_open_for_non_critical_scope(self) -> None:
        from backend.shared.rate_limit import check_rate_limit

        async def fake_cache():
            return _FakeCache(redis=None)

        with patch.dict("os.environ", {"APP_ENV": "production"}, clear=True):
            with patch("backend.shared.rate_limit.get_cache_manager", fake_cache):
                result = await check_rate_limit(
                    scope="score:symbol:ip",
                    identity="ip:1",
                    limit=60,
                    window_seconds=60,
                    fail_closed=False,
                )

        self.assertTrue(result.allowed)
        self.assertEqual(result.count, 0)

    async def test_redis_operation_failure_falls_back_to_memory_in_development(self) -> None:
        from backend.shared.rate_limit import check_rate_limit

        async def fake_cache():
            return _FakeCache(redis=_FailingRedis())

        with patch.dict("os.environ", {"APP_ENV": "development"}, clear=True):
            with patch("backend.shared.rate_limit.get_cache_manager", fake_cache):
                result = await check_rate_limit(
                    scope="auth:login:ip",
                    identity="ip:redis-closed",
                    limit=5,
                    window_seconds=60,
                    fail_closed=True,
                )

        self.assertTrue(result.allowed)
        self.assertEqual(result.count, 1)

    async def test_redis_operation_failure_fail_closed_in_production(self) -> None:
        from backend.shared.rate_limit import check_rate_limit

        async def fake_cache():
            return _FakeCache(redis=_FailingRedis())

        with patch.dict("os.environ", {"APP_ENV": "production"}, clear=True):
            with patch("backend.shared.rate_limit.get_cache_manager", fake_cache):
                with self.assertRaises(HTTPException) as ctx:
                    await check_rate_limit(
                        scope="auth:login:ip",
                        identity="ip:redis-closed",
                        limit=5,
                        window_seconds=60,
                        fail_closed=True,
                    )

        self.assertEqual(ctx.exception.status_code, 503)

    def test_identity_helpers_are_stable(self) -> None:
        from backend.shared.rate_limit import client_ip, user_identity

        request = SimpleNamespace(headers={"x-forwarded-for": "10.0.0.1, 10.0.0.2"}, client=SimpleNamespace(host="127.0.0.1"))
        self.assertEqual(client_ip(request), "10.0.0.1")
        self.assertEqual(user_identity(SimpleNamespace(id=42)), "user:42")


class RateLimitIntegrationContractTests(unittest.TestCase):
    ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]

    def test_auth_alerts_and_score_routes_call_rate_limiter(self) -> None:
        files_and_scopes = {
            "backend/services/user_service/app/api/v1/auth.py": (
                "auth:register:ip",
                "auth:login:ip",
                "auth:me:user",
            ),
            "backend/services/market_service/app/api/v1/alerts.py": (
                "alerts:check:user",
            ),
            "backend/services/analysis_service/api/v1/scoring.py": (
                "score:symbol:ip",
                "score:symbol:ip_symbol",
                "score:recommend:ip",
                "score:recommend:force_refresh:ip",
            ),
        }

        for rel_path, scopes in files_and_scopes.items():
            source = (self.ROOT / rel_path).read_text(encoding="utf-8")
            self.assertIn("enforce_rate_limit", source)
            for scope in scopes:
                self.assertIn(scope, source)


if __name__ == "__main__":
    unittest.main()
