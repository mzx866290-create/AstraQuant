from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from backend.services.analysis_service.engine import scoring_data


def _module(name: str, **attrs) -> ModuleType:
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


class _FakeBreaker:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.call_count = 0

    async def call(self, func):
        self.call_count += 1
        if self.error is not None:
            raise self.error
        return await func()


class _EastMoneySource:
    instances = []
    kline_response = []
    kline_error: Exception | None = None
    money_flow_response = []
    money_flow_error: Exception | None = None

    def __init__(self) -> None:
        self.calls = []
        self.closed = False
        self.__class__.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.kline_response = []
        cls.kline_error = None
        cls.money_flow_response = []
        cls.money_flow_error = None

    async def fetch_daily_kline(self, symbol: str):
        self.calls.append(("fetch_daily_kline", symbol))
        if self.__class__.kline_error is not None:
            raise self.__class__.kline_error
        return self.__class__.kline_response

    async def fetch_money_flow(self, symbol: str, limit: int = 20):
        self.calls.append(("fetch_money_flow", symbol, limit))
        if self.__class__.money_flow_error is not None:
            raise self.__class__.money_flow_error
        return self.__class__.money_flow_response

    async def close(self) -> None:
        self.closed = True
        self.calls.append(("close",))


class _SinaTencentSource:
    instances = []
    response = []
    error: Exception | None = None

    def __init__(self) -> None:
        self.calls = []
        self.__class__.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.response = []
        cls.error = None

    async def fetch_daily_kline(self, symbol: str):
        self.calls.append(("fetch_daily_kline", symbol))
        if self.__class__.error is not None:
            raise self.__class__.error
        return self.__class__.response


def _source_modules() -> dict[str, ModuleType]:
    return {
        "backend.services.data_crawler.sources.eastmoney_source": _module(
            "eastmoney_source",
            EastMoneySource=_EastMoneySource,
        ),
        "backend.services.data_crawler.sources.sina_tencent_source": _module(
            "sina_tencent_source",
            SinaTencentSource=_SinaTencentSource,
        ),
    }


class _Column:
    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)

    def __ge__(self, other):
        return ("ge", self.name, other)

    def desc(self):
        return ("desc", self.name)


class FinancialReport:
    stock_symbol = _Column("stock_symbol")
    report_date = _Column("report_date")


class StockNews:
    stock_symbol = _Column("stock_symbol")
    publish_time = _Column("publish_time")


class _FakeQuery:
    def __init__(self, session, model) -> None:
        self.session = session
        self.model = model

    @property
    def model_name(self) -> str:
        return self.model.__name__

    def filter(self, *criteria):
        self.session.filters.append((self.model_name, criteria))
        return self

    def order_by(self, *criteria):
        self.session.order_bys.append((self.model_name, criteria))
        return self

    def limit(self, value: int):
        self.session.limits.append((self.model_name, value))
        return self

    def all(self):
        error = self.session.errors_by_model.get(self.model_name)
        if error is not None:
            raise error
        return self.session.rows_by_model.get(self.model_name, [])


class _FakeSession:
    def __init__(
        self,
        rows_by_model: dict[str, list] | None = None,
        errors_by_model: dict[str, Exception] | None = None,
    ) -> None:
        self.rows_by_model = rows_by_model or {}
        self.errors_by_model = errors_by_model or {}
        self.queries = []
        self.filters = []
        self.order_bys = []
        self.limits = []
        self.closed = False

    def query(self, model):
        self.queries.append(model.__name__)
        return _FakeQuery(self, model)

    def close(self) -> None:
        self.closed = True


def _database_modules(session: _FakeSession) -> dict[str, ModuleType]:
    return {
        "backend.shared.database": _module(
            "database",
            SessionLocal=lambda: session,
        ),
        "backend.shared.models": _module(
            "models",
            FinancialReport=FinancialReport,
            StockNews=StockNews,
        ),
    }


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 5, 7, 12, 0, 0)
        if tz is not None:
            return value.replace(tzinfo=tz)
        return value


class ScoringDataSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        _EastMoneySource.reset()
        _SinaTencentSource.reset()

    def test_fetch_recent_kline_returns_truncated_primary_data_and_closes_source(self) -> None:
        _EastMoneySource.kline_response = [{"close": idx} for idx in range(5)]
        eastmoney_breaker = _FakeBreaker()
        sina_breaker = _FakeBreaker()

        with (
            patch.dict(sys.modules, _source_modules()),
            patch.object(
                scoring_data,
                "kline_breakers",
                {"eastmoney": eastmoney_breaker, "sina": sina_breaker},
            ),
        ):
            result = asyncio.run(scoring_data.fetch_recent_kline("600519.SH", count=3))

        self.assertEqual(result, [{"close": 2}, {"close": 3}, {"close": 4}])
        self.assertEqual(eastmoney_breaker.call_count, 1)
        self.assertEqual(sina_breaker.call_count, 0)
        self.assertEqual(_EastMoneySource.instances[0].calls, [("fetch_daily_kline", "600519.SH"), ("close",)])
        self.assertTrue(_EastMoneySource.instances[0].closed)
        self.assertEqual(_SinaTencentSource.instances, [])

    def test_fetch_recent_kline_falls_back_to_sina_after_primary_failure(self) -> None:
        _EastMoneySource.kline_error = RuntimeError("eastmoney down")
        _SinaTencentSource.response = [{"close": idx} for idx in range(1, 5)]

        with (
            patch.dict(sys.modules, _source_modules()),
            patch.object(
                scoring_data,
                "kline_breakers",
                {"eastmoney": _FakeBreaker(), "sina": _FakeBreaker()},
            ),
        ):
            result = asyncio.run(scoring_data.fetch_recent_kline("000001.SZ", count=2))

        self.assertEqual(result, [{"close": 3}, {"close": 4}])
        self.assertTrue(_EastMoneySource.instances[0].closed)
        self.assertEqual(_SinaTencentSource.instances[0].calls, [("fetch_daily_kline", "000001.SZ")])

    def test_fetch_recent_kline_skips_open_primary_circuit_and_uses_sina(self) -> None:
        _SinaTencentSource.response = [{"close": 11.0}]
        eastmoney_breaker = _FakeBreaker(scoring_data.CircuitBreakerOpenError("open"))
        sina_breaker = _FakeBreaker()

        with (
            patch.dict(sys.modules, _source_modules()),
            patch.object(
                scoring_data,
                "kline_breakers",
                {"eastmoney": eastmoney_breaker, "sina": sina_breaker},
            ),
        ):
            result = asyncio.run(scoring_data.fetch_recent_kline("600000.SH", count=5))

        self.assertEqual(result, [{"close": 11.0}])
        self.assertEqual(_EastMoneySource.instances, [])
        self.assertEqual(_SinaTencentSource.instances[0].calls, [("fetch_daily_kline", "600000.SH")])
        self.assertEqual(eastmoney_breaker.call_count, 1)
        self.assertEqual(sina_breaker.call_count, 1)

    def test_fetch_recent_kline_raises_combined_source_errors(self) -> None:
        _EastMoneySource.kline_error = RuntimeError("east down")
        _SinaTencentSource.error = RuntimeError("sina down")

        with (
            patch.dict(sys.modules, _source_modules()),
            patch.object(
                scoring_data,
                "kline_breakers",
                {"eastmoney": _FakeBreaker(), "sina": _FakeBreaker()},
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "eastmoney: east down; sina: sina down"):
                asyncio.run(scoring_data.fetch_recent_kline("600519.SH", count=3))

        self.assertTrue(_EastMoneySource.instances[0].closed)

    def test_fetch_financial_reports_maps_rows_and_closes_session(self) -> None:
        report_date = datetime(2026, 3, 31)
        row = SimpleNamespace(
            report_date=report_date,
            report_type="Q1",
            revenue=100.0,
            revenue_yoy=1.2,
            net_profit=20.0,
            net_profit_yoy=2.3,
            gross_margin=30.4,
            net_margin=12.5,
            operating_cf=15.0,
            total_assets=1000.0,
            total_liabilities=300.0,
            total_equity=700.0,
            roe=8.8,
            roa=4.4,
            pe_ttm=16.8,
            pb=2.1,
        )
        session = _FakeSession(rows_by_model={"FinancialReport": [row]})

        with patch.dict(sys.modules, _database_modules(session)):
            result = scoring_data.fetch_financial_reports("600519.SH")

        self.assertEqual(
            result,
            [
                {
                    "report_date": report_date,
                    "report_type": "Q1",
                    "revenue": 100.0,
                    "revenue_yoy": 1.2,
                    "net_profit": 20.0,
                    "net_profit_yoy": 2.3,
                    "gross_margin": 30.4,
                    "net_margin": 12.5,
                    "operating_cf": 15.0,
                    "total_assets": 1000.0,
                    "total_liabilities": 300.0,
                    "total_equity": 700.0,
                    "roe": 8.8,
                    "roa": 4.4,
                    "pe_ttm": 16.8,
                    "pb": 2.1,
                }
            ],
        )
        self.assertEqual(session.queries, ["FinancialReport"])
        self.assertEqual(session.filters, [("FinancialReport", (("eq", "stock_symbol", "600519"),))])
        self.assertEqual(session.order_bys, [("FinancialReport", (("desc", "report_date"),))])
        self.assertEqual(session.limits, [("FinancialReport", 8)])
        self.assertTrue(session.closed)

    def test_fetch_recent_news_maps_rows_filters_cutoff_and_closes_session(self) -> None:
        publish_time = datetime(2026, 5, 7, 10, 30, 0)
        row = SimpleNamespace(
            title="Unit news",
            summary="Mapped summary",
            source="unit-source",
            publish_time=publish_time,
            sentiment="positive",
            sentiment_score=0.7,
            impact_level="low",
            event_category="operations",
            keywords=None,
        )
        session = _FakeSession(rows_by_model={"StockNews": [row]})

        with (
            patch.dict(sys.modules, _database_modules(session)),
            patch.object(scoring_data, "datetime", _FixedDateTime),
        ):
            result = scoring_data.fetch_recent_news("000001.SZ", days=3)

        self.assertEqual(
            result,
            [
                {
                    "title": "Unit news",
                    "summary": "Mapped summary",
                    "source": "unit-source",
                    "publish_time": publish_time,
                    "sentiment": "positive",
                    "sentiment_score": 0.7,
                    "impact_score": 2,
                    "impact_level": "low",
                    "event_category": "operations",
                    "keywords": [],
                }
            ],
        )
        self.assertEqual(session.queries, ["StockNews"])
        self.assertEqual(
            session.filters,
            [
                (
                    "StockNews",
                    (
                        ("eq", "stock_symbol", "000001"),
                        ("ge", "publish_time", datetime(2026, 5, 4, 12, 0, 0)),
                    ),
                )
            ],
        )
        self.assertEqual(session.order_bys, [("StockNews", (("desc", "publish_time"),))])
        self.assertEqual(session.limits, [("StockNews", 100)])
        self.assertTrue(session.closed)

    def test_build_money_flow_context_marks_ok_and_unavailable_quality(self) -> None:
        data = [{"main_inflow": 100.0}]
        ok = scoring_data.build_money_flow_context(data, source="eastmoney")

        self.assertEqual(ok["status"], "ok")
        self.assertEqual(ok["source"], "eastmoney")
        self.assertEqual(ok["data"], data)
        self.assertEqual(ok["warnings"], [])
        self.assertEqual(ok["data_quality"]["confidence"], 0.8)
        self.assertEqual(ok["data_quality"]["freshness"], "latest_available")

        unavailable = scoring_data.build_money_flow_context(
            [],
            source="unit",
            warning="unit_warning",
            message="unit message",
            confidence=0.25,
        )

        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unavailable["warnings"], ["unit_warning"])
        self.assertEqual(unavailable["data_quality"]["warning"], "unit_warning")
        self.assertEqual(unavailable["data_quality"]["warnings"], ["unit_warning"])
        self.assertEqual(unavailable["data_quality"]["message"], "unit message")
        self.assertEqual(unavailable["data_quality"]["confidence"], 0.25)

    def test_fetch_money_flow_returns_ok_context_and_closes_source(self) -> None:
        _EastMoneySource.money_flow_response = [{"date": "2026-05-07", "main_inflow": 1200.0}]
        breaker = _FakeBreaker()

        with (
            patch.dict(sys.modules, _source_modules()),
            patch.object(scoring_data, "money_flow_breaker", breaker),
        ):
            context = asyncio.run(scoring_data.fetch_money_flow("600519", days=7))

        self.assertEqual(context["status"], "ok")
        self.assertEqual(context["source"], "eastmoney")
        self.assertEqual(context["data"], _EastMoneySource.money_flow_response)
        self.assertEqual(context["warnings"], [])
        self.assertEqual(_EastMoneySource.instances[0].calls, [("fetch_money_flow", "600519", 7), ("close",)])
        self.assertTrue(_EastMoneySource.instances[0].closed)
        self.assertEqual(breaker.call_count, 1)

    def test_fetch_money_flow_marks_empty_source_response(self) -> None:
        _EastMoneySource.money_flow_response = []

        with (
            patch.dict(sys.modules, _source_modules()),
            patch.object(scoring_data, "money_flow_breaker", _FakeBreaker()),
        ):
            context = asyncio.run(scoring_data.fetch_money_flow("600519", days=20))

        self.assertEqual(context["status"], "unavailable")
        self.assertEqual(context["warnings"], [scoring_data.MONEY_FLOW_EMPTY_WARNING])
        self.assertEqual(context["data_quality"]["confidence"], 0.05)
        self.assertTrue(_EastMoneySource.instances[0].closed)

    def test_fetch_money_flow_marks_source_error_and_closes_source(self) -> None:
        _EastMoneySource.money_flow_error = RuntimeError("money flow down")

        with (
            patch.dict(sys.modules, _source_modules()),
            patch.object(scoring_data, "money_flow_breaker", _FakeBreaker()),
        ):
            context = asyncio.run(scoring_data.fetch_money_flow("600519", days=20))

        self.assertEqual(context["status"], "unavailable")
        self.assertEqual(context["warnings"], [scoring_data.MONEY_FLOW_SOURCE_ERROR_WARNING])
        self.assertIn("money flow down", context["data_quality"]["message"])
        self.assertTrue(_EastMoneySource.instances[0].closed)

    def test_fetch_money_flow_marks_circuit_open_without_instantiating_source(self) -> None:
        breaker = _FakeBreaker(scoring_data.CircuitBreakerOpenError("open"))

        with (
            patch.dict(sys.modules, _source_modules()),
            patch.object(scoring_data, "money_flow_breaker", breaker),
        ):
            context = asyncio.run(scoring_data.fetch_money_flow("600519", days=20))

        self.assertEqual(context["status"], "unavailable")
        self.assertEqual(context["warnings"], [scoring_data.MONEY_FLOW_CIRCUIT_OPEN_WARNING])
        self.assertIn("open", context["data_quality"]["message"])
        self.assertEqual(_EastMoneySource.instances, [])
        self.assertEqual(breaker.call_count, 1)


if __name__ == "__main__":
    unittest.main()
