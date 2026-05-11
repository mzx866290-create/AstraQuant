from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.risk_veto import evaluate_risk_veto


class RiskVetoTests(unittest.TestCase):
    def _base_stock(self) -> dict:
        return {
            "symbol": "600001.SH",
            "name": "Unit Stock",
            "price": 12.0,
            "kline_data": [{"close": 12.0, "volume": 1000}],
            "readiness": {"data_grade": {"grade": "B"}},
        }

    def test_hard_veto_triggers_for_st_name(self) -> None:
        stock_data = {
            "symbol": "600001.SH",
            "name": "ST示例",
            "price": 12.0,
            "kline_data": [{"close": 12.0, "volume": 1000}],
            "readiness": {"data_grade": {"grade": "B"}},
        }

        result = evaluate_risk_veto(stock_data, {}, {"filters": {"min_data_grade": "C"}})

        self.assertFalse(result["passed"])
        self.assertEqual(result["level"], "hard")
        self.assertEqual(result["veto_reason"], "st_risk")

    def test_hard_veto_triggers_for_data_grade_below_strategy_requirement(self) -> None:
        stock_data = {
            "symbol": "600001.SH",
            "name": "示例股份",
            "price": 12.0,
            "kline_data": [{"close": 12.0, "volume": 1000}],
            "readiness": {"data_grade": {"grade": "C"}},
        }

        result = evaluate_risk_veto(stock_data, {}, {"filters": {"min_data_grade": "B"}})

        self.assertFalse(result["passed"])
        self.assertEqual(result["veto_reason"], "data_grade_below_strategy_minimum")

    def test_soft_warning_keeps_candidate_when_only_yellow_lights_exist(self) -> None:
        stock_data = {
            "symbol": "600001.SH",
            "name": "示例股份",
            "price": 12.0,
            "kline_data": [{"close": 12.0, "volume": 1000}],
            "financial": {"operating_cf": -1},
            "readiness": {"data_grade": {"grade": "B"}},
        }
        risk_lights = {"liquidity": {"level": "yellow", "message": "成交波动偏大"}}

        result = evaluate_risk_veto(stock_data, risk_lights, {"filters": {"min_data_grade": "C"}})

        self.assertTrue(result["passed"])
        self.assertEqual(result["level"], "soft")
        self.assertGreaterEqual(len(result["warnings"]), 2)

    def test_default_risk_light_behavior_is_unchanged(self) -> None:
        risk_lights = {
            "data": {"level": "red", "message": "quote broken"},
            "valuation": {"level": "yellow", "message": "valuation missing"},
        }

        result = evaluate_risk_veto(self._base_stock(), risk_lights, {"filters": {"min_data_grade": "C"}})

        self.assertFalse(result["passed"])
        self.assertEqual(result["veto_reason"], "data")
        self.assertEqual(result["vetoes"][0]["severity"], "hard")
        self.assertEqual(result["warnings"][0]["type"], "valuation")
        self.assertEqual(result["warnings"][0]["severity"], "soft")

    def test_strategy_can_promote_yellow_light_to_hard(self) -> None:
        risk_lights = {"valuation": {"level": "yellow", "message": "valuation missing"}}
        strategy = {
            "filters": {"min_data_grade": "C"},
            "risk_policy": {
                "by_key": {
                    "valuation": {
                        "severity": "hard",
                        "score_delta": -12,
                        "handling": "exclude valuation gaps",
                    }
                }
            },
        }

        result = evaluate_risk_veto(self._base_stock(), risk_lights, strategy)

        self.assertFalse(result["passed"])
        self.assertEqual(result["veto_reason"], "valuation")
        self.assertEqual(result["vetoes"][0]["score_delta"], -12)
        self.assertEqual(result["vetoes"][0]["handling"], "exclude valuation gaps")

    def test_strategy_can_demote_red_light_to_soft(self) -> None:
        risk_lights = {"news": {"level": "red", "message": "negative news"}}
        strategy = {
            "filters": {"min_data_grade": "C"},
            "risk_policy": {"by_key": {"news": {"severity": "soft", "score_delta": -6}}},
        }

        result = evaluate_risk_veto(self._base_stock(), risk_lights, strategy)

        self.assertTrue(result["passed"])
        self.assertEqual(result["level"], "soft")
        self.assertEqual(result["warnings"][0]["type"], "news")
        self.assertEqual(result["warnings"][0]["severity"], "soft")
        self.assertEqual(result["warnings"][0]["score_delta"], -6)

    def test_system_hard_risks_cannot_be_demoted_by_policy(self) -> None:
        strategy = {
            "filters": {"min_data_grade": "D"},
            "risk_policy": {
                "by_type": {
                    "st_risk": {"severity": "soft"},
                    "data_grade_unusable": {"severity": "soft"},
                }
            },
        }
        stock_data = self._base_stock()
        stock_data["name"] = "ST Unit"
        stock_data["readiness"] = {"data_grade": {"grade": "D"}}

        result = evaluate_risk_veto(stock_data, {}, strategy)

        self.assertFalse(result["passed"])
        severities = {item["type"]: item["severity"] for item in result["vetoes"]}
        self.assertEqual(severities["st_risk"], "hard")
        self.assertEqual(severities["data_grade_unusable"], "hard")


if __name__ == "__main__":
    unittest.main()
