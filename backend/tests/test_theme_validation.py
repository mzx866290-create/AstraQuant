from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.theme_validation import build_theme_validation


class ThemeValidationTests(unittest.TestCase):
    def test_build_theme_validation_verifies_theme_with_announcement_and_financials(self) -> None:
        stock_data = {
            "sector": "计算机",
            "industry_event_context": {
                "themes": [
                    {
                        "theme": "AI算力与数字经济",
                        "confidence": "high",
                        "evidence": [{"title": "AI算力政策", "source": "unit", "publish_time": "2026-05-10"}],
                    },
                    {"theme": "数据中心", "confidence": "medium", "evidence": []},
                ]
            },
            "announcements": [
                {"title": "公司取得算力项目订单并推进交付", "announce_date": "2026-05-08", "category": "公告"}
            ],
            "financial": {"revenue_yoy": 12.0, "net_profit_yoy": 5.0},
        }

        result = build_theme_validation(stock_data, {"id": "event_driven"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["theme_heat"]["level"], "high")
        self.assertEqual(result["business_relevance"]["level"], "direct")
        self.assertEqual(result["verification"]["level"], "verified")
        self.assertEqual(result["concept_risk"]["level"], "low")

    def test_build_theme_validation_flags_unverified_hot_theme(self) -> None:
        stock_data = {
            "sector": "计算机",
            "industry_event_context": {
                "themes": [
                    {"theme": "AI算力与数字经济", "confidence": "high", "evidence": [{"title": "AI新闻"}]},
                    {"theme": "大模型", "confidence": "high", "evidence": []},
                ]
            },
            "announcements": [],
            "financial": {},
        }

        result = build_theme_validation(stock_data, {"id": "event_driven"})

        self.assertEqual(result["verification"]["level"], "unverified")
        self.assertIn("hot_theme_may_be_concept_hype", result["concept_risk"]["warnings"])

    def test_build_theme_validation_handles_missing_theme(self) -> None:
        result = build_theme_validation({"sector": "银行", "industry_event_context": {}}, {"id": "value_quality"})

        self.assertEqual(result["status"], "no_theme")
        self.assertEqual(result["concept_risk"]["level"], "unknown")


if __name__ == "__main__":
    unittest.main()
