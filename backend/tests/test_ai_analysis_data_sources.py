from __future__ import annotations

import asyncio
from datetime import date
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.analysis_service.engine import ai_analysis_data


def _module(name: str, **attrs) -> ModuleType:
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


class _Query:
    def __init__(self, session, model) -> None:
        self.session = session
        self.model = model

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def first(self):
        if self.model.__name__ == "Stock":
            return self.session.stock
        return None

    def all(self):
        model_name = self.model.__name__
        if model_name == "FinancialReport":
            return self.session.financial_reports
        if model_name == "CompanyAnnouncement":
            return self.session.announcements
        if model_name == "StockNews":
            self.session.stock_news_query_count += 1
            return self.session.stock_news
        return []


class _Session:
    def __init__(
        self,
        *,
        stock=None,
        financial_reports=None,
        announcements=None,
        stock_news=None,
    ) -> None:
        self.stock = stock
        self.financial_reports = financial_reports or []
        self.announcements = announcements or []
        self.stock_news = stock_news or []
        self.stock_news_query_count = 0
        self.commit_count = 0
        self.closed = False

    def query(self, model):
        return _Query(self, model)

    def commit(self) -> None:
        self.commit_count += 1

    def close(self) -> None:
        self.closed = True


def _financial_row(**overrides):
    values = {
        "report_date": date(2026, 3, 31),
        "report_type": "Q1",
        "revenue": 10_000_000,
        "revenue_yoy": 1.2,
        "net_profit": 2_000_000,
        "net_profit_yoy": 2.3,
        "gross_margin": 30.1,
        "net_margin": 12.3,
        "eps": 0.5,
        "bvps": 3.2,
        "roe": 8.8,
        "roa": 4.4,
        "total_assets": 100_000_000,
        "total_liabilities": 40_000_000,
        "total_equity": 60_000_000,
        "operating_cf": 1_500_000,
        "pe_ttm": None,
        "pb": None,
        "source": "report-db",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _ProfileFrame:
    empty = False

    def iterrows(self):
        rows = [
            {"item": "\u80a1\u7968\u7b80\u79f0", "value": "AkName"},
            {"item": "\u884c\u4e1a", "value": "Chip"},
            {"item": "\u4e0a\u5e02\u65f6\u95f4", "value": "20200102"},
        ]
        for idx, row in enumerate(rows):
            yield idx, row


class AIAnalysisDataSourceTests(unittest.TestCase):
    def test_get_stock_data_orchestrates_session_profile_kline_and_synthetic_quote(self) -> None:
        stock = SimpleNamespace(name="600519", sector="")
        session = _Session(
            stock=stock,
            financial_reports=[_financial_row(pe_ttm=16.8, pb=4.2)],
            announcements=[
                SimpleNamespace(
                    title="Annual report",
                    summary="Stable operations",
                    announce_date=date(2026, 4, 1),
                    category="annual",
                    source="cninfo",
                    content_url="https://example.test/ann",
                )
            ],
        )
        kline = [
            {"date": "2026-04-28", "open": 8, "high": 11, "low": 7, "close": 10, "volume": 1000},
            {"date": "2026-04-29", "open": 10, "high": 13, "low": 9, "close": 12, "volume": 1200},
        ]

        with (
            patch.object(ai_analysis_data, "SessionLocal", return_value=session),
            patch.object(
                ai_analysis_data,
                "fetch_quote",
                new=AsyncMock(return_value={"price": 0, "name": "QuoteName"}),
            ) as fetch_quote,
            patch.object(
                ai_analysis_data,
                "fetch_public_profile",
                new=AsyncMock(return_value={"name": "ProfileName", "sector": "Baijiu", "source": "fake-profile"}),
            ) as fetch_profile,
            patch.object(
                ai_analysis_data,
                "fetch_kline",
                new=AsyncMock(return_value=(kline, "sina-secondary")),
            ) as fetch_kline,
        ):
            result = asyncio.run(ai_analysis_data.get_stock_data("600519.SH", include_news=False))

        self.assertEqual(result["name"], "ProfileName")
        self.assertEqual(result["sector"], "Baijiu")
        self.assertEqual(result["price"], 12.0)
        self.assertEqual(result["change_pct"], 20.0)
        self.assertEqual(result["quote_source"], "synthetic-from-kline")
        self.assertEqual(result["quote"]["kline_source"], "sina-secondary")
        self.assertTrue(result["quote"]["synthetic"])
        self.assertEqual(result["kline_source"], "sina-secondary")
        self.assertEqual(result["indicators"]["latest_price"], 12.0)
        self.assertEqual(result["financial"]["valuation_source"], "report-db")
        self.assertEqual(result["announcements"][0]["title"], "Annual report")
        self.assertEqual(result["industry_event_context"]["warnings"], ["news_disabled"])
        self.assertEqual(stock.name, "ProfileName")
        self.assertEqual(stock.sector, "Baijiu")
        self.assertEqual(session.commit_count, 1)
        self.assertTrue(session.closed)
        fetch_quote.assert_awaited_once_with("600519.SH")
        fetch_profile.assert_awaited_once_with("600519", {"price": 0, "name": "QuoteName"})
        fetch_kline.assert_awaited_once_with("600519.SH", "600519")

    def test_fetch_quote_falls_back_to_next_source_and_marks_source(self) -> None:
        calls = []

        class SinaTencentSource:
            async def fetch_realtime_quote(self, symbol):
                calls.append(("sina", symbol))
                return {"price": 0}

        class EastMoneySource:
            async def fetch_realtime_quote(self, symbol):
                calls.append(("eastmoney", symbol))
                return {"price": "18.5", "name": "FallbackName"}

            async def close(self):
                calls.append(("eastmoney.close", None))

        class AKShareSource:
            async def fetch_realtime_quote(self, symbol):
                calls.append(("akshare", symbol))
                return {"price": "19.5"}

        modules = {
            "backend.services.data_crawler.sources.sina_tencent_source": _module(
                "sina_tencent_source", SinaTencentSource=SinaTencentSource
            ),
            "backend.services.data_crawler.sources.eastmoney_source": _module(
                "eastmoney_source", EastMoneySource=EastMoneySource
            ),
            "backend.services.data_crawler.sources.akshare_source": _module(
                "akshare_source", AKShareSource=AKShareSource
            ),
        }

        with patch.dict(sys.modules, modules):
            result = asyncio.run(ai_analysis_data.fetch_quote("000001.SZ"))

        self.assertEqual(result["price"], "18.5")
        self.assertEqual(result["source"], "eastmoney")
        self.assertEqual(calls, [("sina", "000001.SZ"), ("eastmoney", "000001.SZ"), ("eastmoney.close", None)])

    def test_fetch_public_profile_prefers_akshare_and_marks_source(self) -> None:
        akshare = _module("akshare", stock_individual_info_em=lambda symbol: _ProfileFrame())
        requests = _module("requests", get=lambda *_args, **_kwargs: self.fail("requests should not be called"))

        with patch.dict(sys.modules, {"akshare": akshare, "requests": requests}):
            result = asyncio.run(ai_analysis_data.fetch_public_profile("000001", {"name": "QuoteName"}))

        self.assertEqual(
            result,
            {
                "code": "000001",
                "name": "AkName",
                "sector": "Chip",
                "list_date": "2020-01-02",
                "source": "akshare",
            },
        )

    def test_fetch_public_profile_falls_back_to_eastmoney_after_akshare_failure(self) -> None:
        calls = []

        class Response:
            def raise_for_status(self):
                calls.append("raise_for_status")

            def json(self):
                return {
                    "jbzl": [{"SECURITY_NAME_ABBR": "EmName", "EM2016": "Finance-Bank"}],
                    "fxxg": [{"LISTING_DATE": "2021-05-06T00:00:00"}],
                }

        def get(url, **kwargs):
            calls.append((url, kwargs["params"]["code"]))
            return Response()

        akshare = _module(
            "akshare",
            stock_individual_info_em=lambda symbol: (_ for _ in ()).throw(RuntimeError("akshare down")),
        )
        requests = _module("requests", get=get)

        with patch.dict(sys.modules, {"akshare": akshare, "requests": requests}):
            result = asyncio.run(ai_analysis_data.fetch_public_profile("600000", {"name": "QuoteName"}))

        self.assertEqual(result["name"], "EmName")
        self.assertEqual(result["sector"], "Finance")
        self.assertEqual(result["list_date"], "2021-05-06")
        self.assertEqual(result["source"], "eastmoney")
        self.assertEqual(calls[0][1], "SH600000")
        self.assertEqual(calls[1], "raise_for_status")

    def test_fetch_public_profile_keeps_quote_source_when_public_sources_fail(self) -> None:
        akshare = _module(
            "akshare",
            stock_individual_info_em=lambda symbol: (_ for _ in ()).throw(RuntimeError("akshare down")),
        )
        requests = _module(
            "requests",
            get=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("eastmoney down")),
        )

        with patch.dict(sys.modules, {"akshare": akshare, "requests": requests}):
            result = asyncio.run(ai_analysis_data.fetch_public_profile("000001", {"name": "QuoteName"}))

        self.assertEqual(result["name"], "QuoteName")
        self.assertEqual(result["sector"], "")
        self.assertEqual(result["source"], "quote")

    def test_fetch_kline_uses_clickhouse_primary_when_available(self) -> None:
        class Client:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def execute(self, query, params):
                self.query = query
                self.params = params
                return [
                    (date(2026, 4, 30), 10, 12, 9, 11, 1000),
                    (date(2026, 4, 29), 9, 11, 8, 10, 900),
                ]

        with patch.dict(sys.modules, {"clickhouse_driver": _module("clickhouse_driver", Client=Client)}):
            data, source = asyncio.run(ai_analysis_data.fetch_kline("600000.SH", "600000"))

        self.assertEqual(source, "clickhouse-primary")
        self.assertEqual([row["date"] for row in data], ["2026-04-29", "2026-04-30"])
        self.assertEqual(data[-1]["close"], 11.0)

    def test_fetch_kline_falls_back_to_secondary_source_and_marks_source(self) -> None:
        calls = []

        class Client:
            def __init__(self, **_kwargs):
                calls.append("clickhouse")
                raise RuntimeError("no clickhouse")

        class SinaTencentSource:
            async def fetch_daily_kline(self, symbol):
                calls.append(("sina", symbol))
                return []

        class EastMoneySource:
            async def fetch_daily_kline(self, symbol):
                calls.append(("eastmoney", symbol))
                return [{"date": str(idx), "close": idx} for idx in range(1, 65)]

            async def close(self):
                calls.append("eastmoney.close")

        modules = {
            "clickhouse_driver": _module("clickhouse_driver", Client=Client),
            "backend.services.data_crawler.sources.sina_tencent_source": _module(
                "sina_tencent_source", SinaTencentSource=SinaTencentSource
            ),
            "backend.services.data_crawler.sources.eastmoney_source": _module(
                "eastmoney_source", EastMoneySource=EastMoneySource
            ),
        }

        with patch.dict(sys.modules, modules):
            data, source = asyncio.run(ai_analysis_data.fetch_kline("000001.SZ", "000001"))

        self.assertEqual(source, "eastmoney-secondary")
        self.assertEqual(len(data), 60)
        self.assertEqual(data[0]["close"], 5)
        self.assertEqual(data[-1]["close"], 64)
        self.assertEqual(calls, ["clickhouse", ("sina", "000001.SZ"), ("eastmoney", "000001.SZ"), "eastmoney.close"])

    def test_fetch_kline_returns_source_unavailable_when_every_source_fails(self) -> None:
        class Client:
            def __init__(self, **_kwargs):
                raise RuntimeError("no clickhouse")

        class SinaTencentSource:
            async def fetch_daily_kline(self, symbol):
                raise RuntimeError("sina down")

        class EastMoneySource:
            async def fetch_daily_kline(self, symbol):
                raise RuntimeError("eastmoney down")

            async def close(self):
                pass

        modules = {
            "clickhouse_driver": _module("clickhouse_driver", Client=Client),
            "backend.services.data_crawler.sources.sina_tencent_source": _module(
                "sina_tencent_source", SinaTencentSource=SinaTencentSource
            ),
            "backend.services.data_crawler.sources.eastmoney_source": _module(
                "eastmoney_source", EastMoneySource=EastMoneySource
            ),
        }

        with patch.dict(sys.modules, modules):
            data, source = asyncio.run(ai_analysis_data.fetch_kline("000001.SZ", "000001"))

        self.assertEqual(data, [])
        self.assertEqual(source, "source-unavailable")

    def test_map_financial_keeps_existing_valuation_source_when_quote_is_invalid(self) -> None:
        latest = _financial_row(pe_ttm="14.2", pb=None, source="report-db")
        quote = {"pe_ttm": "bad", "pb": 0, "total_mv": 500, "circ_mv": 300, "source": "quote-source"}

        mapped = ai_analysis_data.map_financial(latest, quote)

        self.assertEqual(mapped["pe_ttm"], "14.2")
        self.assertIsNone(mapped["pb"])
        self.assertEqual(mapped["total_mv"], 500)
        self.assertEqual(mapped["circ_mv"], 300)
        self.assertEqual(mapped["valuation_source"], "report-db")

    def test_map_financial_leaves_valuation_source_unset_when_no_valid_ratios_exist(self) -> None:
        latest = _financial_row(report_date=None, report_type=None, pe_ttm=None, pb=0, source="")
        quote = {"pe_ttm": None, "pb": "not-a-number", "source": "quote-source"}

        mapped = ai_analysis_data.map_financial(latest, quote)

        self.assertEqual(mapped["report_date"], "")
        self.assertEqual(mapped["report_type"], "")
        self.assertEqual(mapped["source"], "akshare")
        self.assertNotIn("valuation_source", mapped)


if __name__ == "__main__":
    unittest.main()
