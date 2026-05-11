from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.services.analysis_service.engine import strategy_rule_scoring as scoring


class StrategyRuleScoringTests(unittest.TestCase):
    def test_default_retail_affordability_rule_scores_price_buckets(self) -> None:
        ideal = scoring.evaluate_rule({"price": 18.5}, "retail_affordability", scoring.DEFAULT_SCORING_RULES["retail_affordability"])
        unavailable = scoring.evaluate_rule({"price": 0}, "retail_affordability", scoring.DEFAULT_SCORING_RULES["retail_affordability"])
        too_high = scoring.evaluate_rule({"price": 88}, "retail_affordability", scoring.DEFAULT_SCORING_RULES["retail_affordability"])

        self.assertEqual(ideal["label"], "single_lot_cost")
        self.assertEqual(ideal["delta"], 14)
        self.assertEqual(ideal["status"], "positive")
        self.assertEqual(ideal["bucket"], "ideal")
        self.assertEqual(ideal["value"], 18.5)

        self.assertEqual(unavailable["delta"], -25)
        self.assertEqual(unavailable["bucket"], "missing")
        self.assertEqual(unavailable["status"], "negative")

        self.assertEqual(too_high["delta"], -18)
        self.assertEqual(too_high["bucket"], "too_high")

    def test_default_market_cap_rule_uses_total_or_circulating_market_value_in_yi(self) -> None:
        ideal = scoring.evaluate_rule(
            {"financial": {"total_mv": 12_000_000_000}},
            "market_cap",
            scoring.DEFAULT_SCORING_RULES["market_cap"],
        )
        fallback_to_circ_mv = scoring.evaluate_rule(
            {"quote": {"circ_mv": 1_500_000_000}},
            "market_cap",
            scoring.DEFAULT_SCORING_RULES["market_cap"],
        )
        missing = scoring.evaluate_rule(
            {"quote": {"total_mv": 0}, "financial": {}},
            "market_cap",
            scoring.DEFAULT_SCORING_RULES["market_cap"],
        )

        self.assertEqual(ideal["delta"], 10)
        self.assertEqual(ideal["bucket"], "ideal")
        self.assertEqual(ideal["value"], 120.0)

        self.assertEqual(fallback_to_circ_mv["delta"], -8)
        self.assertEqual(fallback_to_circ_mv["bucket"], "too_small")
        self.assertEqual(fallback_to_circ_mv["value"], 15.0)

        self.assertEqual(missing["delta"], -3)
        self.assertEqual(missing["bucket"], "missing")
        self.assertIsNone(missing["value"])

    def test_default_valuation_rule_scores_pe_pb_and_reports_matched_values(self) -> None:
        reasonable = scoring.evaluate_rule(
            {"financial": {"pe_ttm": "22.5", "pb": "2.4"}},
            "valuation",
            scoring.DEFAULT_SCORING_RULES["valuation"],
        )
        expensive = scoring.evaluate_rule(
            {"quote": {"pe_ttm": 96, "pb": 3}},
            "valuation",
            scoring.DEFAULT_SCORING_RULES["valuation"],
        )
        missing = scoring.evaluate_rule(
            {"financial": {"pe_ttm": 18}},
            "valuation",
            scoring.DEFAULT_SCORING_RULES["valuation"],
        )

        self.assertEqual(reasonable["delta"], 10)
        self.assertEqual(reasonable["bucket"], "reasonable")
        self.assertEqual(reasonable["pe"], 22.5)
        self.assertEqual(reasonable["pb"], 2.4)
        self.assertEqual(reasonable["value"], {"pe": 22.5, "pb": 2.4})

        self.assertEqual(expensive["delta"], -8)
        self.assertEqual(expensive["bucket"], "expensive")

        self.assertEqual(missing["delta"], -4)
        self.assertEqual(missing["bucket"], "missing")
        self.assertIsNone(missing["value"])

    def test_default_data_quality_rule_scores_grade_buckets(self) -> None:
        grade_a = scoring.evaluate_rule(
            {"readiness": {"data_grade": {"grade": "A"}}},
            "data_quality",
            scoring.DEFAULT_SCORING_RULES["data_quality"],
        )
        grade_c = scoring.evaluate_rule(
            {"readiness": {"data_grade": {"grade": "C"}}},
            "data_quality",
            scoring.DEFAULT_SCORING_RULES["data_quality"],
        )
        missing = scoring.evaluate_rule({}, "data_quality", scoring.DEFAULT_SCORING_RULES["data_quality"])

        self.assertEqual(grade_a["delta"], 12)
        self.assertEqual(grade_a["status"], "positive")
        self.assertEqual(grade_a["value"], "A")

        self.assertEqual(grade_c["delta"], 2)
        self.assertEqual(grade_c["status"], "warning")
        self.assertEqual(grade_c["bucket"], "basic")

        self.assertEqual(missing["delta"], 0)
        self.assertEqual(missing["status"], "warning")
        self.assertEqual(missing["value"], "D")

    def test_default_technical_rule_scores_stable_overextended_weak_and_insufficient_paths(self) -> None:
        stable_kline = [{"close": 38 + i * 0.08, "volume": 1000} for i in range(20)]
        overextended_kline = [{"close": 10, "volume": 1000} for _ in range(15)] + [
            {"close": 10},
            {"close": 11},
            {"close": 12},
            {"close": 13},
            {"close": 14},
        ]
        weak_kline = [{"close": 20, "volume": 1000} for _ in range(19)] + [{"close": 16}]

        stable = scoring.evaluate_rule(
            {"kline_data": stable_kline},
            "technical",
            scoring.DEFAULT_SCORING_RULES["technical"],
        )
        overextended = scoring.evaluate_rule(
            {"kline_data": overextended_kline},
            "technical",
            scoring.DEFAULT_SCORING_RULES["technical"],
        )
        weak = scoring.evaluate_rule(
            {"kline_data": weak_kline},
            "technical",
            scoring.DEFAULT_SCORING_RULES["technical"],
        )
        insufficient = scoring.evaluate_rule(
            {"kline_data": stable_kline[:5]},
            "technical",
            scoring.DEFAULT_SCORING_RULES["technical"],
        )

        self.assertEqual(stable["delta"], 13)
        self.assertEqual(stable["bucket"], "stable")
        self.assertIn("ret5", stable)

        self.assertEqual(overextended["delta"], -8)
        self.assertEqual(overextended["bucket"], "overextended")

        self.assertEqual(weak["delta"], -6)
        self.assertEqual(weak["bucket"], "weak")

        self.assertEqual(insufficient["delta"], 0)
        self.assertEqual(insufficient["status"], "warning")

    def test_technical_rule_supports_strategy_json_bucket_schema(self) -> None:
        rule = {
            "close_window": 20,
            "stable": {"ret5_min": -3, "ret5_max": 12, "ret20_min": -8, "delta": 21},
            "overextended": {"ret5_min": 18, "delta": -9},
            "weak": {"ret20_max": -15, "delta": -7},
            "default": {"delta": 1},
        }
        stable_kline = [{"close": 38 + i * 0.08, "volume": 1000} for i in range(20)]

        result = scoring.evaluate_rule({"kline_data": stable_kline}, "technical", rule)

        self.assertEqual(result["delta"], 21)
        self.assertEqual(result["bucket"], "stable")

    def test_default_volume_rule_scores_moderate_improvement_and_neutral_paths(self) -> None:
        improving = [{"volume": 1000, "close": 10} for _ in range(5)] + [{"volume": 1500, "close": 10} for _ in range(5)]
        excessive = [{"volume": 1000, "close": 10} for _ in range(5)] + [{"volume": 4000, "close": 10} for _ in range(5)]

        hit = scoring.evaluate_rule({"kline_data": improving}, "volume", scoring.DEFAULT_SCORING_RULES["volume"])
        neutral = scoring.evaluate_rule({"kline_data": excessive}, "volume", scoring.DEFAULT_SCORING_RULES["volume"])

        self.assertEqual(hit["delta"], 5)
        self.assertEqual(hit["bucket"], "moderate_improvement")
        self.assertEqual(hit["ratio"], 1.5)

        self.assertEqual(neutral["delta"], 0)
        self.assertEqual(neutral["bucket"], "neutral")

    def test_default_financial_quality_rule_aggregates_component_impacts(self) -> None:
        result = scoring.evaluate_rule(
            {"financial": {"revenue_yoy": 12.5, "net_profit_yoy": 8.1, "operating_cf": -100}},
            "financial_quality",
            scoring.DEFAULT_SCORING_RULES["financial_quality"],
        )

        self.assertEqual(result["delta"], 5)
        self.assertEqual([item["key"] for item in result["components"]], [
            "financial_revenue",
            "financial_profit",
            "financial_cashflow",
        ])
        self.assertEqual([item["delta"] for item in result["components"]], [4, 6, -5])

    def test_default_financial_quality_rule_penalizes_missing_financials(self) -> None:
        result = scoring.evaluate_rule({}, "financial_quality", scoring.DEFAULT_SCORING_RULES["financial_quality"])

        self.assertEqual(result["delta"], -5)
        self.assertEqual(result["components"][0]["key"], "financial")
        self.assertEqual(result["components"][0]["bucket"], "missing")

    def test_configured_rule_result_uses_strategy_scoring_rules_over_defaults(self) -> None:
        strategy = {
            "id": "unit_strategy",
            "scoring_rules": {
                "retail_affordability": {
                    "label": "unit price rule",
                    "value": "price",
                    "items": [
                        {"min": 10, "max": 20, "delta": 31, "bucket": "unit_hit", "message": "custom price hit"},
                        {"delta": -7, "bucket": "unit_fallback", "message": "custom price fallback"},
                    ],
                }
            },
        }

        with patch.object(scoring, "load_strategy", return_value=strategy):
            result = scoring.configured_rule_result({"price": 15}, "unit_strategy", "retail_affordability")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["label"], "unit price rule")
        self.assertEqual(result["delta"], 31)
        self.assertEqual(result["bucket"], "unit_hit")
        self.assertEqual(result["message"], "custom price hit")

    def test_configured_rule_result_supports_custom_factor_from_strategy_json(self) -> None:
        strategy = {
            "id": "unit_strategy",
            "scoring_rules": {
                "momentum_quality": {
                    "label": "momentum quality",
                    "value": "momentum_score",
                    "items": [
                        {"min": 80, "delta": 12, "bucket": "strong", "status": "warning"},
                        {"delta": -5, "bucket": "weak"},
                    ],
                }
            },
        }

        with patch.object(scoring, "load_strategy", return_value=strategy):
            result = scoring.configured_rule_result({"momentum_score": 85}, "unit_strategy", "momentum_quality")
            missing_factor = scoring.configured_rule_result({"momentum_score": 85}, "unit_strategy", "not_configured")

        self.assertEqual(
            result,
            {
                "key": "momentum_quality",
                "label": "momentum quality",
                "delta": 12,
                "status": "warning",
                "message": "momentum_quality: strong",
                "bucket": "strong",
                "value": 85.0,
            },
        )
        self.assertIsNone(missing_factor)

    def test_configured_rule_result_falls_back_to_default_rules_when_strategy_load_fails(self) -> None:
        with patch.object(scoring, "load_strategy", side_effect=KeyError("missing")):
            result = scoring.configured_rule_result({"price": 18}, "missing_strategy", "retail_affordability")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["delta"], 14)
        self.assertEqual(result["bucket"], "ideal")


if __name__ == "__main__":
    unittest.main()
