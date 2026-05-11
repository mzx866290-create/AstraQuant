from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.strategy_config import list_strategy_ids, load_strategy, resolve_strategy


class StrategyConfigTests(unittest.TestCase):
    def test_list_strategy_ids_includes_auto_and_phase1_strategies(self) -> None:
        strategy_ids = list_strategy_ids()
        self.assertIn("auto", strategy_ids)
        self.assertIn("retail_small", strategy_ids)
        self.assertIn("value_quality", strategy_ids)
        self.assertIn("growth_momentum", strategy_ids)

    def test_load_strategy_maps_quality_alias_to_value_quality(self) -> None:
        strategy = load_strategy("quality")
        self.assertEqual(strategy["id"], "value_quality")
        self.assertEqual(strategy["engine_strategy"], "quality")

    def test_strategy_weights_are_normalized_when_present(self) -> None:
        strategy = load_strategy("retail_small")
        self.assertTrue(strategy["weights"])
        self.assertAlmostEqual(sum(strategy["weights"].values()), 1.0, places=5)
        self.assertIn("technical", strategy["weights"])

    def test_resolve_strategy_auto_uses_market_regime_suggestion(self) -> None:
        strategy = resolve_strategy(
            "auto",
            {"regime": "strong_trend", "suggested_strategies": ["growth_momentum"], "confidence": "high"},
        )
        self.assertEqual(strategy["id"], "growth_momentum")
        self.assertEqual(strategy["selection_mode"], "auto")
        self.assertEqual(strategy["selection_reason"], "market_regime:strong_trend")

    def test_resolve_strategy_auto_falls_back_when_regime_is_low_confidence(self) -> None:
        strategy = resolve_strategy("auto", {"regime": "range_bound", "suggested_strategies": [], "confidence": "low"})
        self.assertEqual(strategy["id"], "retail_small")
        self.assertEqual(strategy["selection_mode"], "auto")


if __name__ == "__main__":
    unittest.main()
