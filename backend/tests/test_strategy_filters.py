from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.strategy_filters import evaluate_strategy_filters


class StrategyFiltersTests(unittest.TestCase):
    def test_evaluate_strategy_filters_passes_when_candidate_matches_ranges_and_score(self) -> None:
        result = evaluate_strategy_filters(
            {"price": 20, "total_mv": 100 * 1e8, "strategy_score": 68},
            {
                "filters": {"price_range": [3, 80], "market_cap_range_yi": [20, 1500]},
                "score_threshold": 60,
            },
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["level"], "none")

    def test_evaluate_strategy_filters_blocks_out_of_range_price_and_market_cap(self) -> None:
        result = evaluate_strategy_filters(
            {"price": 120, "total_mv": 10 * 1e8, "strategy_score": 80},
            {
                "filters": {"price_range": [3, 80], "market_cap_range_yi": [20, 1500]},
                "score_threshold": 60,
            },
        )

        self.assertFalse(result["passed"])
        self.assertEqual({item["type"] for item in result["hard"]}, {"price_range_out_of_range", "market_cap_range_yi_out_of_range"})

    def test_evaluate_strategy_filters_blocks_below_strategy_score_threshold(self) -> None:
        result = evaluate_strategy_filters(
            {"price": 20, "total_mv": 100 * 1e8, "strategy_score": 58},
            {
                "filters": {"price_range": [3, 80], "market_cap_range_yi": [20, 1500]},
                "score_threshold": 60,
            },
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["hard"][0]["type"], "score_below_strategy_threshold")


if __name__ == "__main__":
    unittest.main()
