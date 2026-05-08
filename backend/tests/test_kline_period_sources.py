from __future__ import annotations

import asyncio
import inspect
import sys
import types
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.services.market_service.app.api.v1 import kline
from backend.services.market_service.app.services import kline_service


class FakeEastMoneyKlineSource:
    instances = []
    response = []

    def __init__(self) -> None:
        self.calls = []
        self.closed = False
        self.__class__.instances.append(self)

    async def fetch_kline(
        self,
        symbol: str,
        period: str = "1d",
        start_date: str = "",
        end_date: str = "",
        adjust: str = "1",
        limit: int = 500,
    ):
        self.calls.append({
            "symbol": symbol,
            "period": period,
            "adjust": adjust,
            "limit": limit,
        })
        return self.__class__.response

    async def close(self):
        self.closed = True


class FakeSinaDailySource:
    response = []

    async def fetch_daily_kline(self, symbol: str):
        return self.__class__.response


class KlinePeriodSourceTests(unittest.TestCase):
    def test_router_delegates_kline_loading_to_service_layer(self) -> None:
        source = inspect.getsource(kline.get_kline)

        self.assertIn("kline_service.load_kline_data", source)
        self.assertIn("kline_service.build_data_quality", source)
        self.assertNotIn("_fetch_daily_kline", source)
        self.assertNotIn("_aggregate_kline", source)
        self.assertIs(kline._build_local_kline, kline_service.build_local_kline)

    def test_weekly_kline_uses_native_eastmoney_period(self) -> None:
        FakeEastMoneyKlineSource.instances = []
        FakeEastMoneyKlineSource.response = [
            {
                "date": "2026-05-01",
                "open": 10.0,
                "close": 11.0,
                "high": 11.5,
                "low": 9.8,
                "volume": 1000,
                "turnover": 10000.0,
                "change_pct": 2.1,
            }
        ]
        fake_module = types.SimpleNamespace(EastMoneySource=FakeEastMoneyKlineSource)

        with patch.dict(
            sys.modules,
            {"backend.services.data_crawler.sources.eastmoney_source": fake_module},
        ):
            result = asyncio.run(kline.get_kline("600519", period=kline.KLinePeriod.WEEKLY, limit=20))

        self.assertEqual(result["period"], "1w")
        self.assertEqual(result["source"], "eastmoney")
        self.assertEqual(result["data"], FakeEastMoneyKlineSource.response)
        self.assertEqual(FakeEastMoneyKlineSource.instances[0].calls[0]["period"], "1w")
        self.assertTrue(FakeEastMoneyKlineSource.instances[0].closed)
        self.assertFalse(result["data_quality"]["is_fallback"])

    def test_monthly_kline_aggregates_daily_source_when_native_period_empty(self) -> None:
        FakeEastMoneyKlineSource.instances = []
        FakeEastMoneyKlineSource.response = []
        FakeSinaDailySource.response = [
            {"date": "2026-04-29", "open": 10, "close": 11, "high": 12, "low": 9, "volume": 100, "turnover": 1000},
            {"date": "2026-04-30", "open": 11, "close": 12, "high": 13, "low": 10, "volume": 200, "turnover": 2000},
            {"date": "2026-05-06", "open": 12, "close": 13, "high": 14, "low": 11, "volume": 300, "turnover": 3000},
        ]
        fake_em = types.SimpleNamespace(EastMoneySource=FakeEastMoneyKlineSource)
        fake_sina = types.SimpleNamespace(SinaTencentSource=FakeSinaDailySource)

        with patch.dict(
            sys.modules,
            {
                "backend.services.data_crawler.sources.eastmoney_source": fake_em,
                "backend.services.data_crawler.sources.sina_tencent_source": fake_sina,
            },
        ):
            result = asyncio.run(kline.get_kline("600519", period=kline.KLinePeriod.MONTHLY, limit=20))

        self.assertEqual(result["period"], "1M")
        self.assertEqual(result["source"], "sina-tencent-aggregated")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["data"][0]["date"], "2026-04-30")
        self.assertEqual(result["data"][0]["open"], 10)
        self.assertEqual(result["data"][0]["close"], 12)
        self.assertEqual(result["data"][0]["volume"], 300)
        self.assertIn("aggregated from daily source", result["data_quality"]["warnings"][0])

    def test_intraday_kline_uses_eastmoney_minute_source(self) -> None:
        FakeEastMoneyKlineSource.instances = []
        FakeEastMoneyKlineSource.response = [
            {
                "date": "2026-05-06 09:35",
                "open": 10.0,
                "close": 10.2,
                "high": 10.3,
                "low": 9.9,
                "volume": 800,
                "turnover": 8100.0,
                "change_pct": 0.3,
            }
        ]
        fake_module = types.SimpleNamespace(EastMoneySource=FakeEastMoneyKlineSource)

        with patch.dict(
            sys.modules,
            {"backend.services.data_crawler.sources.eastmoney_source": fake_module},
        ):
            result = asyncio.run(kline.get_kline("600519", period=kline.KLinePeriod.MIN_5, limit=20))

        self.assertEqual(result["period"], "5m")
        self.assertEqual(result["source"], "eastmoney")
        self.assertEqual(result["data"], FakeEastMoneyKlineSource.response)
        self.assertEqual(FakeEastMoneyKlineSource.instances[0].calls[0]["period"], "5m")
        self.assertTrue(FakeEastMoneyKlineSource.instances[0].closed)
        self.assertFalse(result["data_quality"]["is_fallback"])

    def test_intraday_kline_empty_returns_explicit_unavailable(self) -> None:
        FakeEastMoneyKlineSource.instances = []
        FakeEastMoneyKlineSource.response = []
        fake_module = types.SimpleNamespace(EastMoneySource=FakeEastMoneyKlineSource)

        with self.assertRaises(HTTPException) as ctx:
            with patch.dict(
                sys.modules,
                {"backend.services.data_crawler.sources.eastmoney_source": fake_module},
            ):
                asyncio.run(kline.get_kline("600519", period=kline.KLinePeriod.MIN_5))

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("minute kline source is temporarily unavailable", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
