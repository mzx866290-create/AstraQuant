from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import time
import unittest
from unittest.mock import AsyncMock, patch

import pandas as pd

from backend.shared import cache
from backend.shared.validators import StockDataValidator, validate_email, validate_stock_symbol


class _FailingRedis:
    async def get(self, key: str):
        return "{not-json"

    async def setex(self, key: str, ttl: int, payload: str) -> None:
        raise RuntimeError("redis write down")

    async def delete(self, *keys: str) -> None:
        raise RuntimeError("redis delete down")

    async def scan(self, cursor: int, match: str):
        raise RuntimeError("redis scan down")


class CacheBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_client = cache.redis_client
        self.original_unavailable = cache._redis_unavailable
        cache._fallback_memory.clear()

    def tearDown(self) -> None:
        cache.redis_client = self.original_client
        cache._redis_unavailable = self.original_unavailable
        cache._fallback_memory.clear()

    def test_ttl_helpers_clamp_short_values_and_handle_fallback_window(self) -> None:
        self.assertEqual(cache.seconds(timedelta(milliseconds=250)), 1)
        self.assertEqual(cache.seconds(timedelta(seconds=3)), 3)
        self.assertEqual(cache.cache_ttl_seconds("unknown_namespace"), 600)
        self.assertEqual(cache.cache_category_for_kline_period("2h"), "daily_kline")

        current = datetime(2026, 5, 7, 12, 0, 0)

        class _PastMidnight:
            min = datetime.min

            @classmethod
            def combine(cls, *_args, **_kwargs):
                return current - timedelta(seconds=1)

        with patch.object(cache, "datetime", _PastMidnight):
            self.assertEqual(cache.ttl_until_next_day(current), cache.CACHE_TTL_DAILY_RECOMMENDATIONS_MAX)

    def test_redis_get_invalid_json_falls_back_to_memory_entry(self) -> None:
        manager = cache.CacheManager(client=_FailingRedis())
        manager._memory = {
            "stock:quote:600519": {
                "value": {"price": 1688.0},
                "expires": time.time() + 60,
            }
        }

        value = asyncio.run(manager.get("quote", "600519"))

        self.assertEqual(value, {"price": 1688.0})

    def test_redis_set_and_delete_failures_preserve_memory_fallback(self) -> None:
        manager = cache.CacheManager(client=_FailingRedis())
        manager._memory = {}

        asyncio.run(manager.set("quote", "600519", value={"price": 1}, ttl=timedelta(seconds=30)))
        self.assertIn("stock:quote:600519", manager._memory)

        asyncio.run(manager.invalidate("quote", "600519"))
        self.assertNotIn("stock:quote:600519", manager._memory)

    def test_scan_failure_still_applies_memory_pattern_invalidation(self) -> None:
        manager = cache.CacheManager(client=_FailingRedis())
        manager._memory = {
            "stock:quote:600519": {"value": 1, "expires": time.time() + 60},
            "stock:quote:000001": {"value": 2, "expires": time.time() + 60},
            "stock:daily_kline:600519": {"value": 3, "expires": time.time() + 60},
        }

        asyncio.run(manager.invalidate_pattern("stock:quote:*"))

        self.assertEqual(list(manager._memory), ["stock:daily_kline:600519"])

    def test_get_cache_manager_respects_redis_unavailable_flag_and_initializes_once(self) -> None:
        cache.redis_client = None
        cache._redis_unavailable = True

        with patch.object(cache, "init_redis", AsyncMock()) as init_redis:
            manager = asyncio.run(cache.get_cache_manager())

        self.assertIsNone(manager.redis)
        init_redis.assert_not_awaited()

        fake_client = object()

        async def _init_success():
            cache.redis_client = fake_client

        cache.redis_client = None
        cache._redis_unavailable = False
        with patch.object(cache, "init_redis", AsyncMock(side_effect=_init_success)) as init_redis:
            manager = asyncio.run(cache.get_cache_manager())

        self.assertIs(manager.redis, fake_client)
        init_redis.assert_awaited_once()


class ValidatorBoundaryTests(unittest.TestCase):
    def test_validate_continuity_ignores_non_daily_frequency(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02 09:30", "2026-01-02 09:35"]),
                "close": [10.0, 10.1],
            }
        )

        validated, report = StockDataValidator.validate_continuity(df, freq="5m")

        self.assertIs(validated, df)
        self.assertEqual(report["missing_dates"], [])

    def test_volume_and_price_range_edges_do_not_mutate_unrelated_columns(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02"]),
                "close": [10.0],
                "volume": [0],
                "tag": ["keep"],
            }
        )

        volume_validated, volume_report = StockDataValidator.validate_volume(df)
        range_validated, range_report = StockDataValidator.validate_price_range(df)

        self.assertIs(volume_validated, df)
        self.assertEqual(volume_report["issues"], ["零成交量: 1条"])
        self.assertEqual(range_report["issues"], [])
        self.assertEqual(list(range_validated.columns), ["date", "close", "volume", "tag"])

    def test_full_validate_reports_volume_issue_after_ohlc_keeps_valid_rows(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-01-02"),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 0,
                },
                {
                    "date": pd.Timestamp("2026-01-05"),
                    "open": 10.5,
                    "high": 11.5,
                    "low": 10.0,
                    "close": 11.0,
                    "volume": 1000,
                },
            ]
        )

        cleaned, report = StockDataValidator().full_validate(df)

        self.assertEqual(len(cleaned), 2)
        self.assertEqual(report["volume"]["issues"], ["零成交量: 1条"])
        self.assertEqual(report["clean_rows"], 2)

    def test_lenient_string_validators_document_boundary_behavior(self) -> None:
        self.assertTrue(validate_stock_symbol(" 600519 "))
        self.assertFalse(validate_stock_symbol(None))
        self.assertFalse(validate_stock_symbol("X" * 21))

        self.assertTrue(validate_email("@."))
        self.assertFalse(validate_email(None))
        self.assertFalse(validate_email("user@example"))


if __name__ == "__main__":
    unittest.main()
