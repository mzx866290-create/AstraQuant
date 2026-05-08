import asyncio
import unittest
from datetime import date
from unittest.mock import patch

from fastapi import HTTPException

from backend.services.market_service.app.api.v1 import dragon_tiger


class DragonTigerApiTests(unittest.TestCase):
    def test_list_normalizes_akshare_rows_with_quality(self) -> None:
        rows = [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "上榜日": "20260506",
                "上榜原因": "日涨幅偏离值达7%",
                "收盘价": "1668.88",
                "涨跌幅": "8.12",
                "龙虎榜净买额": "120000000.5",
                "龙虎榜买入额": "320000000",
                "龙虎榜卖出额": "200000000",
                "龙虎榜成交额": "520000000",
                "换手率": "1.23",
            }
        ]

        async def fake_fetch(trade_date):
            self.assertEqual(trade_date, date(2026, 5, 6))
            return rows

        with patch.object(dragon_tiger, "_fetch_akshare_dragon_tiger", fake_fetch):
            result = asyncio.run(dragon_tiger.get_dragon_tiger(trade_date=date(2026, 5, 6), limit=20))

        self.assertEqual(result["source"], "akshare-eastmoney")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["data_quality"]["status"], "ok")
        self.assertEqual(result["data"][0]["symbol"], "600519.SH")
        self.assertEqual(result["data"][0]["trade_date"], "2026-05-06")
        self.assertEqual(result["data"][0]["net_buy"], 120000000.5)

    def test_list_empty_returns_unavailable_quality_without_fake_rows(self) -> None:
        async def fake_fetch(_trade_date):
            return []

        with patch.object(dragon_tiger, "_fetch_akshare_dragon_tiger", fake_fetch):
            result = asyncio.run(dragon_tiger.get_dragon_tiger(limit=20))

        self.assertEqual(result["data"], [])
        self.assertEqual(result["data_quality"]["status"], "unavailable")
        self.assertIn("dragon_tiger_empty", result["data_quality"]["warnings"])
        self.assertLess(result["data_quality"]["confidence"], 0.2)

    def test_stock_history_filters_symbol(self) -> None:
        rows = [
            {"代码": "600519", "名称": "贵州茅台", "交易日期": "2026-05-06", "净买额": "100"},
            {"代码": "000001", "名称": "平安银行", "交易日期": "2026-05-06", "净买额": "200"},
        ]

        async def fake_fetch(symbol, days):
            self.assertEqual(symbol, "600519")
            self.assertEqual(days, 60)
            return rows

        with patch.object(dragon_tiger, "_fetch_akshare_stock_dragon_tiger", fake_fetch):
            result = asyncio.run(dragon_tiger.get_stock_dragon_tiger("600519.SH", days=60, limit=20))

        self.assertEqual(result["symbol"], "600519.SH")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["data"][0]["symbol"], "600519.SH")
        self.assertEqual(result["data"][0]["net_buy"], 100.0)

    def test_stock_history_rejects_invalid_symbol(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(dragon_tiger.get_stock_dragon_tiger("BAD"))

        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
