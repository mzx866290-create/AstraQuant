from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import unittest
from unittest.mock import AsyncMock, patch


class FakeRedis:
    def __init__(self) -> None:
        self.setex_calls = []

    async def setex(self, key: str, ttl: int, payload: str) -> None:
        self.setex_calls.append((key, ttl, payload))


class FakeCache:
    def __init__(self, cached=None) -> None:
        self.cached = cached
        self.get_calls = []
        self.set_calls = []

    async def get(self, category: str, key: str):
        self.get_calls.append((category, key))
        return self.cached

    async def set(self, category: str, key: str, value):
        self.set_calls.append((category, key, value))


class FakeCondition:
    def __or__(self, other):
        return self


class FakeField:
    def like(self, pattern: str):
        return FakeCondition()

    def __eq__(self, other):
        return FakeCondition()


class FakeStockModel:
    symbol = FakeField()
    name = FakeField()
    market = FakeField()


class FakeStockRow:
    def __init__(self, symbol: str, name: str, market: str) -> None:
        self.symbol = symbol
        self.name = name
        self.market = market


class FakeQuery:
    def __init__(self, rows) -> None:
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def limit(self, limit: int):
        self.rows = self.rows[:limit]
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.closed = False

    def query(self, model):
        return FakeQuery(list(self.rows))

    def close(self):
        self.closed = True


class CacheTTLPolicyTests(unittest.TestCase):
    def test_resolve_cache_ttl_policy_uses_named_durations(self) -> None:
        from backend.shared.cache import (
            DEFAULT_CACHE_TTL,
            cache_category_for_kline_period,
            resolve_cache_ttl,
        )

        self.assertEqual(resolve_cache_ttl("realtime_quote"), timedelta(seconds=5))
        self.assertEqual(resolve_cache_ttl("minute_kline"), timedelta(minutes=1))
        self.assertEqual(resolve_cache_ttl("daily_kline"), timedelta(hours=24))
        self.assertEqual(resolve_cache_ttl("weekly_kline"), timedelta(days=7))
        self.assertEqual(resolve_cache_ttl("monthly_kline"), timedelta(days=7))
        self.assertEqual(resolve_cache_ttl("search_result"), timedelta(minutes=5))
        self.assertEqual(resolve_cache_ttl("unknown_namespace"), DEFAULT_CACHE_TTL)
        self.assertEqual(cache_category_for_kline_period("5m"), "minute_kline")
        self.assertEqual(cache_category_for_kline_period("1d"), "daily_kline")
        self.assertEqual(cache_category_for_kline_period("1w"), "week_month_kline")
        self.assertEqual(cache_category_for_kline_period("1M"), "week_month_kline")

    def test_daily_recommendations_ttl_expires_at_next_day(self) -> None:
        from backend.shared.cache import resolve_cache_ttl

        now = datetime(2026, 5, 7, 10, 30, 0)

        self.assertEqual(resolve_cache_ttl("daily_recommendations", now), timedelta(hours=13, minutes=30))

    def test_cache_manager_set_uses_namespace_ttl_and_default_ttl(self) -> None:
        from backend.shared.cache import CacheManager

        redis = FakeRedis()
        cache = CacheManager(redis)

        asyncio.run(cache.set("search_result", "ping", value={"ok": True}))
        asyncio.run(cache.set("unknown_namespace", "pong", value={"ok": True}))

        self.assertEqual(redis.setex_calls[0][0], "stock:search_result:ping")
        self.assertEqual(redis.setex_calls[0][1], 300)
        self.assertEqual(redis.setex_calls[1][0], "stock:unknown_namespace:pong")
        self.assertEqual(redis.setex_calls[1][1], 600)

    def test_search_stocks_uses_search_result_cache_namespace(self) -> None:
        from backend.services.market_service.app.api.v1 import search

        cache = FakeCache()
        session = FakeSession([FakeStockRow("600519.SH", "Kweichow Moutai", "SH")])

        with patch("backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)), patch(
            "backend.shared.database.SessionLocal", return_value=session
        ), patch("backend.shared.models.Stock", FakeStockModel):
            result = asyncio.run(search.search_stocks("600519", market="SH", limit=10))

        self.assertEqual(result["total"], 1)
        self.assertEqual(cache.get_calls, [("search_result", "v1:600519:SH:10")])
        self.assertEqual(cache.set_calls[0][0], "search_result")
        self.assertEqual(cache.set_calls[0][1], "v1:600519:SH:10")
        self.assertTrue(session.closed)

    def test_search_stocks_returns_cached_response_without_db(self) -> None:
        from backend.services.market_service.app.api.v1 import search

        cached = {"results": [], "total": 0, "query": "abc"}
        cache = FakeCache(cached=cached)

        with patch("backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)), patch(
            "backend.shared.database.SessionLocal"
        ) as session_local, patch("backend.shared.models.Stock", FakeStockModel):
            result = asyncio.run(search.search_stocks("abc", market=None, limit=5))

        self.assertEqual(result, cached)
        session_local.assert_not_called()
        self.assertEqual(cache.get_calls, [("search_result", "v1:abc:ALL:5")])
        self.assertEqual(cache.set_calls, [])


if __name__ == "__main__":
    unittest.main()
