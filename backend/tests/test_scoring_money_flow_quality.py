from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch


class FakeMoneyFlowSource:
    instances = []
    response = []

    def __init__(self) -> None:
        self.closed = False
        self.calls = []
        self.__class__.instances.append(self)

    async def fetch_money_flow(self, symbol: str, limit: int = 20):
        self.calls.append({"symbol": symbol, "limit": limit})
        return self.__class__.response

    async def close(self) -> None:
        self.closed = True


class ScoringMoneyFlowQualityTests(unittest.TestCase):
    def test_fetch_money_flow_uses_eastmoney_and_closes_source(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        FakeMoneyFlowSource.instances = []
        FakeMoneyFlowSource.response = [
            {"date": "2026-05-06", "main_inflow": 1200.0, "small_inflow": -300.0}
        ]
        fake_module = types.SimpleNamespace(EastMoneySource=FakeMoneyFlowSource)

        with patch.dict(
            sys.modules,
            {"backend.services.data_crawler.sources.eastmoney_source": fake_module},
        ):
            context = asyncio.run(scoring._fetch_money_flow("600519", 20))

        self.assertEqual(context["status"], "ok")
        self.assertEqual(context["source"], "eastmoney")
        self.assertEqual(context["data"], FakeMoneyFlowSource.response)
        self.assertEqual(FakeMoneyFlowSource.instances[0].calls, [{"symbol": "600519", "limit": 20}])
        self.assertTrue(FakeMoneyFlowSource.instances[0].closed)

    def test_fetch_money_flow_marks_empty_eastmoney_response(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        FakeMoneyFlowSource.instances = []
        FakeMoneyFlowSource.response = []
        fake_module = types.SimpleNamespace(EastMoneySource=FakeMoneyFlowSource)

        with patch.dict(
            sys.modules,
            {"backend.services.data_crawler.sources.eastmoney_source": fake_module},
        ):
            context = asyncio.run(scoring._fetch_money_flow("600519", 20))

        self.assertEqual(context["status"], "unavailable")
        self.assertEqual(context["source"], "eastmoney")
        self.assertIn("money_flow_empty", context["warnings"])
        self.assertEqual(context["data_quality"]["confidence"], 0.05)
        self.assertTrue(FakeMoneyFlowSource.instances[0].closed)

    def test_stock_score_marks_money_flow_unavailable(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        kline_data = [{"close": 10 + idx} for idx in range(20)]
        empty_money_flow = scoring._build_money_flow_context(
            [],
            source="eastmoney",
            warning="money_flow_empty",
            message="资金流向数据源暂未返回可用数据，情绪评分不包含资金流因子",
            confidence=0.05,
        )

        with patch.object(
            scoring, "_fetch_recent_kline", AsyncMock(return_value=kline_data)
        ), patch.object(
            scoring, "_fetch_financial_reports", return_value=[]
        ), patch.object(
            scoring, "_fetch_recent_news", return_value=[]
        ), patch.object(
            scoring, "_fetch_money_flow", AsyncMock(return_value=empty_money_flow)
        ), patch.object(
            scoring, "_compute_momentum", return_value={"score": 5.0, "detail": "momentum"}
        ), patch.object(
            scoring, "_compute_technical", return_value={"score": 5.0, "detail": "technical"}
        ), patch.object(
            scoring, "_compute_value", return_value={"score": 5.0, "detail": "value", "source": "insufficient"}
        ), patch.object(
            scoring, "_compute_quality", return_value={"score": 5.0, "detail": "quality", "source": "insufficient"}
        ):
            result = asyncio.run(scoring.get_stock_score("600519"))

        sentiment = result["dimensions"]["sentiment"]
        self.assertEqual(sentiment["status"], "unavailable")
        self.assertEqual(sentiment["source"], "insufficient_without_money_flow")
        self.assertIn("money_flow_empty", sentiment["warnings"])
        self.assertIn("资金流向暂不可用", sentiment["detail"])

        self.assertEqual(result["data_source_summary"]["money_flow_status"], "unavailable")
        self.assertEqual(result["data_source_summary"]["money_flow_source"], "eastmoney")
        self.assertEqual(result["data_quality"]["money_flow"]["status"], "unavailable")
        self.assertIn("money_flow_empty", result["warnings"])


if __name__ == "__main__":
    unittest.main()
