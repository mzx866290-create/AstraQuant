from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest

from backend.services.analysis_service.engine.industry_event_impact import IndustryEventImpactEngine


def _rule_with_keyword(keyword: str) -> dict:
    for rule in IndustryEventImpactEngine.RULES:
        if keyword in rule["keywords"]:
            return rule
    raise AssertionError(f"rule with keyword {keyword!r} not found")


class IndustryEventImpactEngineTests(unittest.TestCase):
    def test_analyze_returns_unavailable_when_market_news_is_missing(self) -> None:
        result = IndustryEventImpactEngine.analyze("Unit Corp", "Unit Sector", [])

        self.assertFalse(result["available"])
        self.assertEqual(result["sector"], "Unit Sector")
        self.assertEqual(result["themes"], [])
        self.assertIn("industry_event_news_missing", result["warnings"])

    def test_analyze_maps_positive_sector_with_high_confidence_evidence(self) -> None:
        rule = _rule_with_keyword("AI")
        sector = rule["positive_sectors"][0]
        news = [
            {
                "title": "AI demand expands",
                "summary": "AI infrastructure orders rise",
                "source": "unit-source",
                "publish_time": "2026-05-07T09:30:00",
                "related_sector": sector,
            },
            {
                "title": "AI computing investment accelerates",
                "summary": "AI chips and data centers remain active",
                "source": "unit-source",
                "publish_time": "2026-05-07T10:30:00",
                "related_sector": sector,
            },
        ]

        result = IndustryEventImpactEngine.analyze("Unit Corp", sector, news)

        self.assertTrue(result["available"])
        theme = result["themes"][0]
        self.assertEqual(theme["theme"], rule["theme"])
        self.assertEqual(theme["direction"], "positive")
        self.assertEqual(theme["confidence"], "high")
        self.assertEqual(len(theme["evidence"]), 2)
        self.assertEqual(theme["evidence"][0]["scope"], "market_news")

    def test_analyze_maps_negative_sector_for_mixed_rule(self) -> None:
        rule = _rule_with_keyword("OPEC")
        sector = rule["negative_sectors"][0]
        news = [
            {
                "title": "OPEC output decision lifts crude price",
                "summary": "OPEC supply cuts pressure downstream margins",
                "source": "unit-source",
                "related_sector": sector,
                "stock_symbol": "600000.SH",
            }
        ]

        result = IndustryEventImpactEngine.analyze("Unit Corp", sector, news)

        self.assertTrue(result["available"])
        theme = result["themes"][0]
        self.assertEqual(theme["theme"], rule["theme"])
        self.assertEqual(theme["direction"], "negative")
        self.assertEqual(theme["confidence"], "medium")
        self.assertEqual(theme["evidence"][0]["scope"], "stock_news_theme")

    def test_analyze_without_sector_can_match_stock_name_and_keyword(self) -> None:
        result = IndustryEventImpactEngine.analyze(
            "UnitAI",
            "",
            [{"title": "UnitAI launches AI service", "summary": "AI adoption expands"}],
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["themes"][0]["confidence"], "low")

    def test_filter_market_news_normalizes_objects_deduplicates_and_respects_limit(self) -> None:
        row = SimpleNamespace(
            title="Policy title",
            stock_symbol="",
            summary="industry update",
            source="unit-source",
            url="https://example.test",
            publish_time=datetime(2026, 5, 7, 9, 30),
            sentiment="neutral",
            sentiment_score=0,
            impact_level="medium",
            event_category="政策",
            related_sector="",
        )
        rows = [
            row,
            {"title": "Policy title", "summary": "duplicate", "event_category": "政策"},
            {"title": "Ignored company detail", "summary": "single stock only"},
            {"title": "AI market title", "summary": "AI broad market update"},
        ]

        filtered = IndustryEventImpactEngine.filter_market_news(rows, limit=2)

        self.assertEqual([item["title"] for item in filtered], ["Policy title", "AI market title"])
        self.assertEqual(filtered[0]["publish_time"], "2026-05-07T09:30:00")


if __name__ == "__main__":
    unittest.main()
