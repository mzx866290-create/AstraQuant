import asyncio
import sys
import types
import unittest
from unittest.mock import patch

from backend.services.market_service.app.api.v1 import quotes


class FakeEmptyEastMoneySource:
    instances = []

    def __init__(self):
        self.closed = False
        self.calls = []
        self.__class__.instances.append(self)

    async def fetch_money_flow(self, symbol: str, limit: int = 20):
        self.calls.append({"symbol": symbol, "limit": limit})
        return []

    async def close(self):
        self.closed = True


class MoneyFlowQualityTests(unittest.TestCase):
    def test_empty_eastmoney_money_flow_returns_empty_quality(self) -> None:
        FakeEmptyEastMoneySource.instances = []
        fake_module = types.SimpleNamespace(EastMoneySource=FakeEmptyEastMoneySource)

        with patch.dict(
            sys.modules,
            {"backend.services.data_crawler.sources.eastmoney_source": fake_module},
        ):
            response = asyncio.run(quotes.get_money_flow("600519", days=20))

        self.assertEqual(response["symbol"], "600519")
        self.assertEqual(response["days"], 20)
        self.assertEqual(response["data"], [])
        self.assertEqual(response["source"], "eastmoney")

        quality = response["data_quality"]
        self.assertEqual(quality["source"], "eastmoney")
        self.assertEqual(quality["status"], "empty")
        self.assertEqual(quality["freshness"], "empty")
        self.assertLessEqual(quality["confidence"], 0.2)
        self.assertEqual(quality["warning"], "money_flow_empty")
        self.assertIn("money_flow_empty", quality["warnings"])

        self.assertEqual(FakeEmptyEastMoneySource.instances[0].calls, [{"symbol": "600519", "limit": 20}])
        self.assertTrue(FakeEmptyEastMoneySource.instances[0].closed)


if __name__ == "__main__":
    unittest.main()
