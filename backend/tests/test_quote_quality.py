from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from backend.services.market_service.app.api.v1 import quotes


class QuoteQualityTests(unittest.TestCase):
    def test_get_quote_prefers_bj_920_alias_for_legacy_code(self) -> None:
        calls: list[str] = []

        class FakeSinaTencentSource:
            async def fetch_realtime_quote(self, symbol: str) -> dict:
                calls.append(symbol)
                return {
                    "symbol": symbol,
                    "name": "诺思兰德",
                    "price": 31.45 if symbol == "920047.BJ" else 8.17,
                    "open": 31.23,
                    "high": 32.19,
                    "low": 30.78,
                    "volume": 4152900,
                    "turnover": 130967100,
                    "turnover_rate": 2.31,
                    "change": 0.0,
                    "change_pct": 0.0,
                    "timestamp": "2026-05-15T15:35:13",
                    "source": "tencent",
                }

        with patch(
            "backend.services.data_crawler.sources.sina_tencent_source.SinaTencentSource",
            FakeSinaTencentSource,
        ):
            result = asyncio.run(quotes.get_quote("430047.BJ"))

        self.assertEqual(calls, ["920047.BJ"])
        self.assertEqual(result["price"], 31.45)
        self.assertEqual(result["requested_symbol"], "430047.BJ")
        self.assertEqual(result["resolved_symbol"], "920047.BJ")
        self.assertEqual(result["data_quality"]["status"], "ok")

    def test_quote_quality_flags_zero_trade_fields_without_hiding_price(self) -> None:
        result = quotes._with_quote_quality(
            {
                "symbol": "430047.BJ",
                "price": 8.17,
                "open": 0,
                "high": 0,
                "low": 0,
                "volume": 0,
                "timestamp": "2026-05-15T09:00:00",
                "source": "tencent",
            },
            "sina-tencent",
            confidence=0.95,
        )

        quality = result["data_quality"]
        self.assertEqual(result["price"], 8.17)
        self.assertEqual(quality["status"], "degraded")
        self.assertEqual(quality["confidence"], 0.65)
        self.assertIn("quote_trade_fields_missing_or_zero", quality["warnings"])
        self.assertIn("quote_volume_zero_or_suspended", quality["warnings"])

    def test_quote_quality_keeps_complete_quote_ok(self) -> None:
        result = quotes._with_quote_quality(
            {
                "symbol": "600519.SH",
                "price": 1332.95,
                "open": 1335.15,
                "high": 1339.28,
                "low": 1327.11,
                "volume": 58184,
                "timestamp": "2026-05-15T16:14:05",
            },
            "sina-tencent",
            confidence=0.95,
        )

        quality = result["data_quality"]
        self.assertEqual(quality["status"], "ok")
        self.assertEqual(quality["confidence"], 0.95)
        self.assertEqual(quality["warnings"], [])


if __name__ == "__main__":
    unittest.main()
