from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.indicator_engine import IndicatorEngine


def _ohlcv(closes: list[float]) -> list[dict]:
    return [
        {
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": close * 100,
        }
        for close in closes
    ]


class IndicatorEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = IndicatorEngine()

    def test_ma_and_volume_ma_use_none_until_period_is_available(self) -> None:
        data = _ohlcv([10, 12, 14, 16])

        self.assertEqual(self.engine.ma(data, period=3), [None, None, 12.0, 14.0])
        self.assertEqual(self.engine.volume_ma(data, period=2), [None, 1100.0, 1300.0, 1500.0])

    def test_ema_seeds_with_sma_then_applies_multiplier(self) -> None:
        data = _ohlcv([10, 12, 14, 16])

        self.assertEqual(self.engine.ema(data, period=3), [None, None, 12.0, 14.0])

    def test_boll_calculates_middle_upper_and_lower_bands(self) -> None:
        data = _ohlcv([1, 2, 3])

        bands = self.engine.boll(data, period=3, multiplier=2)

        self.assertEqual(bands["middle"], [None, None, 2.0])
        self.assertEqual(bands["upper"], [None, None, 3.633])
        self.assertEqual(bands["lower"], [None, None, 0.367])

    def test_kdj_uses_rolling_high_low_and_smoothed_kd_values(self) -> None:
        data = [
            {"high": 11, "low": 9, "close": 10},
            {"high": 14, "low": 10, "close": 13},
            {"high": 15, "low": 11, "close": 14},
        ]

        kdj = self.engine.kdj(data, period=3)

        self.assertEqual(kdj["k"][:2], [None, None])
        self.assertEqual(kdj["d"][:2], [None, None])
        self.assertEqual(kdj["j"][:2], [None, None])
        self.assertAlmostEqual(kdj["k"][2], 61.1111)
        self.assertAlmostEqual(kdj["d"][2], 53.7037)
        self.assertAlmostEqual(kdj["j"][2], 75.9259)

    def test_rsi_returns_100_when_average_loss_is_zero(self) -> None:
        data = _ohlcv([float(value) for value in range(1, 17)])

        rsi = self.engine.rsi(data, period=14)

        self.assertEqual(rsi[:14], [None] * 14)
        self.assertEqual(rsi[14:], [100.0, 100.0])

    def test_macd_returns_aligned_series_and_histogram_formula(self) -> None:
        data = _ohlcv([float(value) for value in range(1, 45)])

        macd = self.engine.macd(data)

        self.assertEqual(set(macd), {"dif", "dea", "histogram"})
        self.assertEqual(len(macd["dif"]), len(data))
        self.assertEqual(len(macd["dea"]), len(data))
        self.assertEqual(len(macd["histogram"]), len(data))
        self.assertIsNotNone(macd["dif"][-1])
        self.assertIsNotNone(macd["dea"][-1])
        self.assertEqual(macd["histogram"][-1], round(2 * (macd["dif"][-1] - macd["dea"][-1]), 4))

    def test_compute_all_routes_supported_indicator_names_and_ignores_unknowns(self) -> None:
        data = _ohlcv([float(value) for value in range(1, 31)])

        result = self.engine.compute_all(data, ["ma3", "ema3", "vol", "macd", "boll", "kdj", "rsi", "unknown"])

        self.assertEqual(set(result), {"ma3", "ema3", "vol", "macd", "boll", "kdj", "rsi"})
        self.assertEqual(result["ma3"][-1], 29.0)
        self.assertEqual(result["vol"][-1], 2800.0)
        self.assertIsInstance(result["macd"], dict)


if __name__ == "__main__":
    unittest.main()
