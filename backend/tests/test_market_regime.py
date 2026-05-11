from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.analysis_service.engine import market_regime


def _kline_from_closes(closes: list[float], volumes: list[float] | None = None) -> list[dict]:
    volumes = volumes or [1000] * len(closes)
    return [{"close": value, "volume": volumes[index]} for index, value in enumerate(closes)]


class MarketRegimeTests(unittest.TestCase):
    def test_detect_market_regime_returns_strong_trend_when_indices_above_mas(self) -> None:
        bullish = _kline_from_closes([100 + i for i in range(60)])
        with patch.object(market_regime, "fetch_recent_kline", AsyncMock(return_value=bullish)):
            result = asyncio.run(market_regime.detect_market_regime())

        self.assertEqual(result["regime"], "strong_trend")
        self.assertIn("growth_momentum", result["suggested_strategies"])
        self.assertTrue(result["signals"])
        self.assertEqual(result["components"]["breadth"], "broad_positive")
        self.assertGreater(result["components"]["trend_score"], 0)

    def test_detect_market_regime_returns_weak_market_when_indices_below_mas(self) -> None:
        bearish = _kline_from_closes([160 - i for i in range(60)])
        with patch.object(market_regime, "fetch_recent_kline", AsyncMock(return_value=bearish)):
            result = asyncio.run(market_regime.detect_market_regime())

        self.assertEqual(result["regime"], "weak_market")
        self.assertIn("value_quality", result["suggested_strategies"])
        self.assertEqual(result["components"]["breadth"], "broad_negative")

    def test_detect_market_regime_degrades_to_low_confidence_when_data_unavailable(self) -> None:
        with patch.object(market_regime, "fetch_recent_kline", AsyncMock(side_effect=RuntimeError("unit down"))):
            result = asyncio.run(market_regime.detect_market_regime())

        self.assertEqual(result["regime"], "range_bound")
        self.assertEqual(result["confidence"], "low")
        self.assertTrue(result["data_quality"]["warnings"])
        self.assertEqual(result["components"]["breadth"], "unknown")

    def test_detect_market_regime_reports_volume_confirmation(self) -> None:
        volumes = [1000] * 55 + [2200] * 5
        bullish = _kline_from_closes([100 + i for i in range(60)], volumes)

        with patch.object(market_regime, "fetch_recent_kline", AsyncMock(return_value=bullish)):
            result = asyncio.run(market_regime.detect_market_regime())

        self.assertEqual(result["components"]["volume"], "confirming_risk_on")
        self.assertGreater(result["components"]["volume_ratio"], 1.0)
        self.assertTrue(any(item["indicator"] == "volume_confirmation" for item in result["signals"]))

    def test_detect_market_regime_uses_growth_risk_appetite_proxy(self) -> None:
        hs300 = _kline_from_closes([100 + i * 0.2 for i in range(60)])
        csi500 = _kline_from_closes([100 + i * 0.4 for i in range(60)])
        chinext = _kline_from_closes([100 + i * 1.0 for i in range(60)])

        async def fake_fetch(symbol: str, _count: int):
            return {
                "000300.SH": hs300,
                "000905.SH": csi500,
                "399006.SZ": chinext,
            }[symbol]

        with patch.object(market_regime, "fetch_recent_kline", AsyncMock(side_effect=fake_fetch)):
            result = asyncio.run(market_regime.detect_market_regime())

        self.assertEqual(result["components"]["risk_appetite"], "growth_risk_on")
        self.assertIn("retail_small", result["suggested_strategies"])


if __name__ == "__main__":
    unittest.main()
