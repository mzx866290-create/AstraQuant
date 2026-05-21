from __future__ import annotations

import asyncio
import sys
import types
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from backend.services.market_service.app.services import kline_service

FRESH_DATE = (datetime.now().date() - timedelta(days=1)).isoformat()

DAILY_ROWS = [
    {"date": "2026-04-30", "open": 10, "close": 11, "high": 12, "low": 9, "volume": 100, "turnover": 1000, "change_pct": 1.0},
    {"date": "2026-05-01", "open": 11, "close": 12, "high": 13, "low": 10, "volume": 200, "turnover": 2000, "change_pct": 2.0},
    {"date": "2026-05-04", "open": 12, "close": 13, "high": 14, "low": 11, "volume": 300, "turnover": 3000, "change_pct": 3.0},
]


class FakeSinaTencentSource:
    response: list[dict] = []
    responses_by_symbol: dict[str, list[dict]] = {}
    error: Exception | None = None
    calls: list[str] = []
    instances: list["FakeSinaTencentSource"] = []

    def __init__(self) -> None:
        self.__class__.instances.append(self)

    async def fetch_daily_kline(self, symbol: str):
        self.__class__.calls.append(symbol)
        if self.__class__.error:
            raise self.__class__.error
        return self.__class__.responses_by_symbol.get(symbol, self.__class__.response)


class FakeEastMoneySource:
    response: list[dict] = []
    error: Exception | None = None
    instances: list["FakeEastMoneySource"] = []

    def __init__(self) -> None:
        self.calls: list[dict] = []
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
        self.calls.append({"symbol": symbol, "period": period, "adjust": adjust, "limit": limit})
        if self.__class__.error:
            raise self.__class__.error
        return self.__class__.response

    async def close(self):
        self.closed = True


class FakeAKShareSource:
    response: list[dict] = []
    error: Exception | None = None
    instances: list["FakeAKShareSource"] = []
    calls: list[dict] = []

    def __init__(self) -> None:
        self.__class__.instances.append(self)

    async def fetch_daily_kline(self, symbol: str, adjust: str = "1"):
        self.__class__.calls.append({"symbol": symbol, "adjust": adjust})
        if self.__class__.error:
            raise self.__class__.error
        return self.__class__.response


class FakeColumn:
    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other):
        return (self.name, "eq", other)

    def desc(self):
        return (self.name, "desc")


class FakeFinancialReportModel:
    stock_symbol = FakeColumn("stock_symbol")
    report_date = FakeColumn("report_date")


class FakeReport:
    def __init__(self, pb, bvps) -> None:
        self.pb = pb
        self.bvps = bvps


class FakeReportQuery:
    def __init__(self, report) -> None:
        self.report = report
        self.filters: list = []
        self.orders: list = []

    def filter(self, condition):
        self.filters.append(condition)
        return self

    def order_by(self, order):
        self.orders.append(order)
        return self

    def first(self):
        return self.report


class FakeSession:
    report = None
    instances: list["FakeSession"] = []

    def __init__(self) -> None:
        self.closed = False
        self.query_model = None
        self.query_obj = None
        self.__class__.instances.append(self)

    def query(self, model):
        self.query_model = model
        self.query_obj = FakeReportQuery(self.__class__.report)
        return self.query_obj

    def close(self):
        self.closed = True


def reset_source_fakes() -> None:
    FakeSinaTencentSource.response = []
    FakeSinaTencentSource.responses_by_symbol = {}
    FakeSinaTencentSource.error = None
    FakeSinaTencentSource.calls = []
    FakeSinaTencentSource.instances = []

    FakeEastMoneySource.response = []
    FakeEastMoneySource.error = None
    FakeEastMoneySource.instances = []

    FakeAKShareSource.response = []
    FakeAKShareSource.error = None
    FakeAKShareSource.calls = []
    FakeAKShareSource.instances = []


def source_modules_patch():
    return patch.dict(
        sys.modules,
        {
            "backend.services.data_crawler.sources.sina_tencent_source": types.SimpleNamespace(SinaTencentSource=FakeSinaTencentSource),
            "backend.services.data_crawler.sources.eastmoney_source": types.SimpleNamespace(EastMoneySource=FakeEastMoneySource),
            "backend.services.data_crawler.sources.akshare_source": types.SimpleNamespace(AKShareSource=FakeAKShareSource),
        },
    )


class KlineLoadServiceTests(unittest.TestCase):
    def test_load_kline_data_daily_uses_daily_source_and_trims_limit(self) -> None:
        async def fake_fetch_daily(symbol: str, adjust: str):
            self.assertEqual(symbol, "600519")
            self.assertEqual(adjust, "hfq")
            return DAILY_ROWS, "sina-tencent"

        async def fail_local(*_args, **_kwargs):
            self.fail("daily data should not use local fallback when a source returns rows")

        with patch.object(kline_service, "fetch_daily_kline", fake_fetch_daily), patch.object(kline_service, "build_local_kline", fail_local):
            data, source = asyncio.run(kline_service.load_kline_data("600519", "1d", "hfq", 2))

        self.assertEqual(source, "sina-tencent")
        self.assertEqual([row["date"] for row in data], ["2026-05-01", "2026-05-04"])

    def test_load_kline_data_aggregates_weekly_and_monthly_when_native_period_empty(self) -> None:
        eastmoney_calls: list[dict] = []

        async def fake_fetch_period(symbol: str, period: str, adjust: str, limit: int = 500):
            eastmoney_calls.append({"symbol": symbol, "period": period, "adjust": adjust, "limit": limit})
            return [], "eastmoney"

        async def fake_fetch_daily(symbol: str, adjust: str):
            self.assertEqual((symbol, adjust), ("600519", "qfq"))
            return DAILY_ROWS, "sina-tencent"

        async def fail_local(*_args, **_kwargs):
            self.fail("aggregated source should not fall back locally when daily rows exist")

        with (
            patch.object(kline_service, "fetch_eastmoney_period_kline", fake_fetch_period),
            patch.object(kline_service, "fetch_daily_kline", fake_fetch_daily),
            patch.object(kline_service, "build_local_kline", fail_local),
        ):
            weekly, weekly_source = asyncio.run(kline_service.load_kline_data("600519", "1w", "qfq", 20))
            monthly, monthly_source = asyncio.run(kline_service.load_kline_data("600519", "1M", "qfq", 20))

        self.assertEqual(weekly_source, "sina-tencent-aggregated")
        self.assertEqual([row["date"] for row in weekly], ["2026-05-01", "2026-05-04"])
        self.assertEqual(weekly[0]["open"], 10)
        self.assertEqual(weekly[0]["close"], 12)
        self.assertEqual(weekly[0]["volume"], 300)

        self.assertEqual(monthly_source, "sina-tencent-aggregated")
        self.assertEqual([row["date"] for row in monthly], ["2026-04-30", "2026-05-04"])
        self.assertEqual(monthly[1]["start_date"], "2026-05-01")

        self.assertEqual([call["period"] for call in eastmoney_calls], ["1w", "1M"])
        self.assertEqual([call["limit"] for call in eastmoney_calls], [20, 20])

    def test_load_kline_data_uses_local_daily_rows_for_weekly_fallback(self) -> None:
        build_calls: list[dict] = []

        async def fake_fetch_period(*_args, **_kwargs):
            return [], "eastmoney"

        async def fake_fetch_daily(*_args, **_kwargs):
            return [], "unavailable"

        async def fake_build_local(symbol: str, limit: int):
            build_calls.append({"symbol": symbol, "limit": limit})
            return DAILY_ROWS

        with (
            patch.object(kline_service, "fetch_eastmoney_period_kline", fake_fetch_period),
            patch.object(kline_service, "fetch_daily_kline", fake_fetch_daily),
            patch.object(kline_service, "build_local_kline", fake_build_local),
        ):
            data, source = asyncio.run(kline_service.load_kline_data("600519", "1w", "qfq", 1))

        self.assertEqual(source, "local-fallback")
        self.assertEqual(build_calls, [{"symbol": "600519", "limit": 7}])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["date"], "2026-05-04")


class KlineQualityAndHelperTests(unittest.TestCase):
    def test_build_data_quality_reports_fallback_aggregation_and_zero_price_warnings(self) -> None:
        fallback_quality = kline_service.build_data_quality(
            "local-fallback",
            "1d",
            [{"date": "2026-05-06", "open": 0, "high": 1, "low": 1, "close": 1}],
        )

        self.assertTrue(fallback_quality["is_fallback"])
        self.assertEqual(fallback_quality["freshness"], "generated")
        self.assertEqual(fallback_quality["confidence"], 0.35)
        self.assertEqual(fallback_quality["updated_at"], "2026-05-06")
        self.assertIn("local fallback kline generated from local financial data; not exchange sourced", fallback_quality["warnings"])
        self.assertIn("one or more kline price fields are 0; source data may be incomplete", fallback_quality["warnings"])

        aggregated_quality = kline_service.build_data_quality(
            "sina-tencent-aggregated",
            "1M",
            [{"date": "2026-05-31", "open": 10, "high": 11, "low": 9, "close": 10.5}],
        )

        self.assertFalse(aggregated_quality["is_fallback"])
        self.assertIn("1M kline aggregated from daily source because native period source was unavailable", aggregated_quality["warnings"])

        stale_quality = kline_service.build_data_quality(
            "sina-tencent-stale",
            "1d",
            [{"date": "2000-01-01", "open": 10, "high": 11, "low": 9, "close": 10.5}],
        )

        self.assertEqual(stale_quality["status"], "degraded")
        self.assertEqual(stale_quality["freshness"], "stale")
        self.assertLess(stale_quality["confidence"], 0.5)
        self.assertIn("kline_stale", stale_quality["warnings"])

    def test_aggregate_kline_rolls_up_rows_and_skips_invalid_dates(self) -> None:
        rows = [
            {"date": "2026-05-01", "open": "10.123", "close": "11.499", "high": "12.49", "low": "9.51", "volume": "100.4", "turnover": "1000.555", "change_pct": "1.234"},
            {"date": "not-a-date", "open": 1, "close": 1, "high": 1, "low": 1, "volume": 1, "turnover": 1, "change_pct": 1},
            {"date": "2026-04-27", "open": "9", "close": "10", "high": "10.5", "low": "8.8", "volume": "50", "turnover": "500", "change_pct": "0.7"},
            {"date": "2026-05-04", "open": "11.5", "close": "12.65", "high": "13", "low": "11", "volume": "200", "turnover": "2500", "change_pct": "10"},
        ]

        self.assertIs(kline_service.aggregate_kline(rows, "1d"), rows)

        weekly = kline_service.aggregate_kline(rows, "1w")

        self.assertEqual(len(weekly), 2)
        self.assertEqual(
            weekly[0],
            {
                "date": "2026-05-01",
                "start_date": "2026-04-27",
                "open": 9.0,
                "close": 11.5,
                "high": 12.49,
                "low": 8.8,
                "volume": 150,
                "turnover": 1500.55,
                "change_pct": 1.23,
            },
        )
        self.assertEqual(weekly[1]["date"], "2026-05-04")
        self.assertEqual(weekly[1]["open"], 11.5)
        self.assertEqual(weekly[1]["close"], 12.65)
        self.assertEqual(weekly[1]["change_pct"], 10.01)

    def test_parse_kline_date_and_safe_float_handle_invalid_values(self) -> None:
        same_date = date(2026, 5, 6)

        self.assertIs(kline_service.parse_kline_date(same_date), same_date)
        self.assertEqual(kline_service.parse_kline_date("2026-05-06T09:30:00"), date(2026, 5, 6))
        self.assertIsNone(kline_service.parse_kline_date(""))
        self.assertIsNone(kline_service.parse_kline_date("20260506"))

        self.assertEqual(kline_service.safe_float("10.5"), 10.5)
        self.assertEqual(kline_service.safe_float(3), 3.0)
        self.assertIsNone(kline_service.safe_float(None))
        self.assertIsNone(kline_service.safe_float("bad"))
        self.assertIsNone(kline_service.safe_float("nan"))
        self.assertIsNone(kline_service.safe_float("inf"))


class KlineFetchSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_source_fakes()

    def test_fetch_daily_kline_prefers_sina_tencent_over_other_sources(self) -> None:
        FakeSinaTencentSource.response = [{"date": FRESH_DATE, "close": 10}]
        FakeEastMoneySource.response = [{"date": FRESH_DATE, "close": 20}]
        FakeAKShareSource.response = [{"date": FRESH_DATE, "close": 30}]

        with source_modules_patch():
            data, source = asyncio.run(kline_service.fetch_daily_kline("600519", "hfq"))

        self.assertEqual(data, FakeSinaTencentSource.response)
        self.assertEqual(source, "sina-tencent")
        self.assertEqual(FakeSinaTencentSource.calls, ["600519"])
        self.assertEqual(FakeEastMoneySource.instances, [])
        self.assertEqual(FakeAKShareSource.instances, [])

    def test_fetch_daily_kline_skips_stale_sina_before_fallback_sources(self) -> None:
        FakeSinaTencentSource.response = [{"date": "2000-01-01", "close": 10}]
        FakeEastMoneySource.response = [{"date": FRESH_DATE, "close": 20}]
        FakeAKShareSource.response = [{"date": FRESH_DATE, "close": 30}]

        with source_modules_patch():
            data, source = asyncio.run(kline_service.fetch_daily_kline("430047.BJ", "qfq"))

        self.assertEqual(data, FakeEastMoneySource.response)
        self.assertEqual(source, "eastmoney")
        self.assertEqual(FakeSinaTencentSource.calls, ["430047.BJ", "920047.BJ"])
        self.assertEqual(FakeEastMoneySource.instances[0].calls, [{"symbol": "430047.BJ", "period": "1d", "adjust": "qfq", "limit": 500}])
        self.assertEqual(FakeAKShareSource.instances, [])

    def test_fetch_daily_kline_uses_bj_920_alias_after_legacy_sina_stale(self) -> None:
        FakeSinaTencentSource.responses_by_symbol = {
            "430047.BJ": [{"date": "2025-09-30", "close": 25.24}],
            "920047.BJ": [{"date": FRESH_DATE, "close": 31.45}],
        }
        FakeEastMoneySource.response = []
        FakeAKShareSource.response = []

        with source_modules_patch():
            data, source = asyncio.run(kline_service.fetch_daily_kline("430047.BJ", "qfq"))

        self.assertEqual(data, FakeSinaTencentSource.responses_by_symbol["920047.BJ"])
        self.assertEqual(source, "sina-tencent-bj920-alias")
        self.assertEqual(FakeSinaTencentSource.calls, ["430047.BJ", "920047.BJ"])

    def test_fetch_daily_kline_returns_stale_sina_when_no_fresh_source_exists(self) -> None:
        FakeSinaTencentSource.response = [{"date": "2000-01-01", "close": 10}]
        FakeEastMoneySource.response = []
        FakeAKShareSource.response = []

        with source_modules_patch():
            data, source = asyncio.run(kline_service.fetch_daily_kline("430047.BJ", "qfq"))

        self.assertEqual(data, FakeSinaTencentSource.response)
        self.assertEqual(source, "sina-tencent-stale")
        self.assertEqual(FakeSinaTencentSource.calls, ["430047.BJ", "920047.BJ"])
        self.assertEqual(FakeAKShareSource.calls, [
            {"symbol": "430047.BJ", "adjust": "qfq"},
            {"symbol": "920047.BJ", "adjust": "qfq"},
        ])

    def test_fetch_daily_kline_uses_eastmoney_before_akshare_after_empty_sina(self) -> None:
        FakeSinaTencentSource.response = []
        FakeEastMoneySource.response = [{"date": FRESH_DATE, "close": 20}]
        FakeAKShareSource.response = [{"date": FRESH_DATE, "close": 30}]

        with source_modules_patch():
            data, source = asyncio.run(kline_service.fetch_daily_kline("600519", "qfq"))

        self.assertEqual(data, FakeEastMoneySource.response)
        self.assertEqual(source, "eastmoney")
        self.assertEqual(FakeSinaTencentSource.calls, ["600519"])
        self.assertEqual(FakeEastMoneySource.instances[0].calls, [{"symbol": "600519", "period": "1d", "adjust": "qfq", "limit": 500}])
        self.assertTrue(FakeEastMoneySource.instances[0].closed)
        self.assertEqual(FakeAKShareSource.instances, [])

    def test_fetch_daily_kline_uses_akshare_after_sina_error_and_empty_eastmoney(self) -> None:
        FakeSinaTencentSource.error = RuntimeError("sina unavailable")
        FakeEastMoneySource.response = []
        FakeAKShareSource.response = [{"date": FRESH_DATE, "close": 30}]

        with source_modules_patch():
            data, source = asyncio.run(kline_service.fetch_daily_kline("600519", "hfq"))

        self.assertEqual(data, FakeAKShareSource.response)
        self.assertEqual(source, "akshare")
        self.assertEqual(FakeSinaTencentSource.calls, ["600519"])
        self.assertEqual(FakeEastMoneySource.instances[0].calls, [{"symbol": "600519", "period": "1d", "adjust": "hfq", "limit": 500}])
        self.assertTrue(FakeEastMoneySource.instances[0].closed)
        self.assertEqual(FakeAKShareSource.calls, [{"symbol": "600519", "adjust": "hfq"}])

    def test_fetch_eastmoney_period_kline_closes_source_on_success_and_error(self) -> None:
        FakeEastMoneySource.response = [{"date": FRESH_DATE, "close": 20}]

        with source_modules_patch():
            data, source = asyncio.run(kline_service.fetch_eastmoney_period_kline("600519", "1w", "qfq", limit=7))

        self.assertEqual(data, FakeEastMoneySource.response)
        self.assertEqual(source, "eastmoney")
        self.assertEqual(FakeEastMoneySource.instances[0].calls, [{"symbol": "600519", "period": "1w", "adjust": "qfq", "limit": 7}])
        self.assertTrue(FakeEastMoneySource.instances[0].closed)

        reset_source_fakes()
        FakeEastMoneySource.error = RuntimeError("boom")

        with source_modules_patch():
            data, source = asyncio.run(kline_service.fetch_eastmoney_period_kline("600519", "1M", "hfq", limit=9))

        self.assertEqual(data, [])
        self.assertEqual(source, "eastmoney")
        self.assertEqual(FakeEastMoneySource.instances[0].calls, [{"symbol": "600519", "period": "1M", "adjust": "hfq", "limit": 9}])
        self.assertTrue(FakeEastMoneySource.instances[0].closed)


class KlineLocalFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeSession.report = None
        FakeSession.instances = []

    def test_build_local_kline_uses_financial_report_when_available_and_defaults_without_report(self) -> None:
        fake_db_module = types.SimpleNamespace(SessionLocal=FakeSession)
        fake_models_module = types.SimpleNamespace(FinancialReport=FakeFinancialReportModel)

        with patch.dict(sys.modules, {"backend.shared.database": fake_db_module, "backend.shared.models": fake_models_module}):
            FakeSession.report = FakeReport(pb=3, bvps=10)
            report_rows = asyncio.run(kline_service.build_local_kline("600519.SH", 3))

            FakeSession.report = None
            fallback_rows = asyncio.run(kline_service.build_local_kline("600519.SH", 3))

        self.assertEqual(len(report_rows), 3)
        self.assertEqual(len(fallback_rows), 3)
        self.assertGreater(report_rows[0]["close"], fallback_rows[0]["close"] + 8)

        report_session, fallback_session = FakeSession.instances
        self.assertIs(report_session.query_model, FakeFinancialReportModel)
        self.assertEqual(report_session.query_obj.filters, [("stock_symbol", "eq", "600519")])
        self.assertEqual(report_session.query_obj.orders, [("report_date", "desc")])
        self.assertTrue(report_session.closed)
        self.assertTrue(fallback_session.closed)
        self.assertGreaterEqual(fallback_rows[0]["close"], 19)
        self.assertLessEqual(fallback_rows[0]["close"], 21)


if __name__ == "__main__":
    unittest.main()
