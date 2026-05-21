from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.strategy_scoring import (
    apply_strategy_weighted_score,
    strategy_factor_key,
)
from backend.services.analysis_service.engine.multiplier_scorer import apply_multiplier_scoring


class StrategyScoringTests(unittest.TestCase):
    def test_multiplier_scoring_keeps_observation_pool_diverse_and_almost_list_wide(self) -> None:
        candidates = []
        for index in range(8):
            candidates.append({
                "symbol": f"00000{index}.SZ",
                "anomaly_score": 90 - index,
                "industry_name": "AI",
            })
        candidates.extend([
            {"symbol": "600001.SH", "anomaly_score": 82, "industry_name": "Banks"},
            {"symbol": "600002.SH", "anomaly_score": 81, "industry_name": "Banks"},
            {"symbol": "300001.SZ", "anomaly_score": 80, "industry_name": "Medicine"},
        ])

        top, almost, summary = apply_multiplier_scoring(
            candidates,
            "2026-05-15",
            top_n=5,
            almost_band=3,
            almost_min=4,
            industry_cap=2,
        )

        industries = [item["industry_name"] for item in top]
        self.assertLessEqual(industries.count("AI"), 2)
        self.assertGreaterEqual(len(almost), 4)
        self.assertEqual(summary["max_per_industry"], 2)
        self.assertEqual(summary["almost_score_band"], 3)

    def test_factor_aliases_map_breakdown_items_to_strategy_dimensions(self) -> None:
        weights = {"financial_quality": 0.4, "sentiment": 0.2, "industry_theme": 0.2, "risk": 0.2}

        self.assertEqual(strategy_factor_key("financial_profit", weights), "financial_quality")
        self.assertEqual(strategy_factor_key("news_sentiment", weights), "sentiment")
        self.assertEqual(strategy_factor_key("industry_events", weights), "industry_theme")
        self.assertEqual(strategy_factor_key("risk_financial", weights), "risk")
        self.assertIsNone(strategy_factor_key("retail_affordability", weights))

    def test_strategy_weights_change_score_direction_conservatively(self) -> None:
        item = {
            "score": 70,
            "score_breakdown": [
                {"key": "base", "delta": 50},
                {"key": "technical", "delta": 20},
                {"key": "valuation", "delta": -12},
            ],
        }

        momentum = apply_strategy_weighted_score(
            item,
            {"id": "growth_momentum", "weights": {"technical": 0.7, "valuation": 0.3}},
        )
        value = apply_strategy_weighted_score(
            item,
            {"id": "value_quality", "weights": {"technical": 0.3, "valuation": 0.7}},
        )

        self.assertEqual(momentum["base_score"], 70)
        self.assertGreater(momentum["strategy_score"], value["strategy_score"])
        self.assertEqual(momentum["score"], momentum["strategy_score"])
        self.assertTrue(momentum["strategy_weighted_factors"])

    def test_strategy_score_is_clamped(self) -> None:
        item = {
            "score": 98,
            "score_breakdown": [
                {"key": "base", "delta": 50},
                {"key": "technical", "delta": 120},
            ],
        }

        result = apply_strategy_weighted_score(item, {"id": "unit", "weights": {"technical": 1.0}})

        self.assertLessEqual(result["strategy_score"], 100)

    def test_default_score_blending_keeps_existing_formula(self) -> None:
        item = {
            "score": 70,
            "score_breakdown": [
                {"key": "base", "delta": 50},
                {"key": "technical", "delta": 20},
            ],
        }

        result = apply_strategy_weighted_score(item, {"id": "unit", "weights": {"technical": 1.0}})

        self.assertEqual(result["strategy_score"], 70)
        self.assertEqual(result["strategy_score_blending"]["base_weight"], 0.65)
        self.assertEqual(result["strategy_score_blending"]["weighted_weight"], 0.35)

    def test_strategy_score_blending_can_change_mix_and_multiplier_bounds(self) -> None:
        item = {
            "score": 70,
            "score_breakdown": [
                {"key": "base", "delta": 50},
                {"key": "technical", "delta": 20},
                {"key": "valuation", "delta": -10},
            ],
        }
        default = apply_strategy_weighted_score(
            item,
            {"id": "default", "weights": {"technical": 0.9, "valuation": 0.1}},
        )
        aggressive = apply_strategy_weighted_score(
            item,
            {
                "id": "aggressive",
                "weights": {"technical": 0.9, "valuation": 0.1},
                "score_blending": {
                    "base_weight": 0.2,
                    "weighted_weight": 0.8,
                    "multiplier_max": 4.0,
                    "multiplier_min": 0.1,
                },
            },
        )

        self.assertGreater(aggressive["strategy_score"], default["strategy_score"])
        top_factor = aggressive["strategy_weighted_factors"][0]
        self.assertEqual(top_factor["factor"], "technical")
        self.assertEqual(top_factor["multiplier"], 1.8)
        self.assertEqual(aggressive["strategy_score_blending"]["base_weight"], 0.2)

    def test_score_blending_normalizes_invalid_mix_weights(self) -> None:
        item = {
            "score": 70,
            "score_breakdown": [
                {"key": "base", "delta": 50},
                {"key": "technical", "delta": 20},
            ],
        }

        result = apply_strategy_weighted_score(
            item,
            {"id": "unit", "weights": {"technical": 1.0}, "score_blending": {"base_weight": 2, "weighted_weight": 1}},
        )

        self.assertAlmostEqual(result["strategy_score_blending"]["base_weight"], 0.666667)
        self.assertAlmostEqual(result["strategy_score_blending"]["weighted_weight"], 0.333333)


if __name__ == "__main__":
    unittest.main()
