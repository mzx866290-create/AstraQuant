from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.anomaly_screener import (
    POOL_PULLBACK,
    POOL_REVERSAL,
    POOL_TREND,
    _evaluate_candidate,
)


def history_from_closes(closes: list[float]) -> list[dict]:
    rows = []
    for index, close in enumerate(closes):
        prev = closes[index + 1] if index + 1 < len(closes) else close
        rows.append(
            {
                "trade_date": f"2026-05-{19 - index:02d}",
                "close": close,
                "prev_close": prev,
                "change_pct": (close / prev - 1) * 100 if prev else 0,
                "volume": 1000000 + index * 1000,
                "turnover_rate": 3.0,
                "ma5": None,
                "ma20": None,
                "ma60": None,
            }
        )
    return rows


def base_item(close: float, ma5: float, ma20: float, ma60: float, change_pct: float) -> dict:
    return {
        "symbol": "000001.SZ",
        "name": "unit",
        "market": "SZ",
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "prev_close": close / (1 + change_pct / 100),
        "change_pct": change_pct,
        "volume": 2000000,
        "turnover": 100000000,
        "turnover_rate": 3.0,
        "total_mv": 5e9,
        "circ_mv": 4e9,
        "vol_ratio_5d": 1.3,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
    }


class AnomalyScreenerBucketTests(unittest.TestCase):
    def test_trend_strength_bucket(self) -> None:
        hist = history_from_closes([11.8 - i * 0.08 for i in range(60)])
        result = _evaluate_candidate(base_item(12.0, 11.8, 11.2, 10.5, 2.0), hist)

        self.assertIsNotNone(result)
        self.assertEqual(result["observation_bucket"], POOL_TREND)

    def test_pullback_support_bucket(self) -> None:
        hist = history_from_closes([10.9, 11.1, 11.3, 11.6, 11.9, 12.0, 11.6, 11.1] + [10.0] * 52)
        result = _evaluate_candidate(base_item(10.7, 10.8, 10.95, 10.1, -1.8), hist)

        self.assertIsNotNone(result)
        self.assertEqual(result["observation_bucket"], POOL_PULLBACK)

    def test_oversold_reversal_bucket(self) -> None:
        hist = history_from_closes([9.8, 10.1, 10.4, 10.8, 11.2, 11.4] + [10.6] * 54)
        result = _evaluate_candidate(base_item(9.7, 9.9, 10.6, 10.1, -1.5), hist)

        self.assertIsNotNone(result)
        self.assertEqual(result["observation_bucket"], POOL_REVERSAL)


if __name__ == "__main__":
    unittest.main()
