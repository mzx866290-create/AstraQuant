from __future__ import annotations

import unittest

from backend.services.analysis_service.engine import ai_analysis_fallbacks


def _risky_stock_data() -> dict:
    return {
        "name": "Unit Corp",
        "price": 10.0,
        "change_pct": -5.5,
        "quote": {"source": "quote-unit"},
        "quote_source": "quote-unit",
        "kline_source": "kline-unit",
        "kline_data": [],
        "financial": {
            "report_date": "2026-03-31",
            "source": "financial-unit",
            "valuation_source": "valuation-unit",
            "revenue": 10_000_000,
            "net_profit": 1_000_000,
            "operating_cf": -500_000,
            "pe_ttm": None,
            "pb": None,
        },
        "announcements": [{"title": "Unit announcement", "announce_date": "2026-05-07"}],
        "news": [{"title": "Unit news", "publish_time": "2026-05-07T09:30:00"}],
        "news_sentiment": {
            "total": 3,
            "weighted_dominant_sentiment": "negative",
            "validation_note": "negative tone",
        },
        "industry_event_context": {
            "available": False,
            "themes": [],
            "warnings": ["industry_event_news_missing"],
            "note": "market news missing",
        },
        "data_quality": {
            "quote": {
                "source": "quote-unit",
                "warnings": ["quote_trade_fields_missing_or_zero"],
            },
            "kline": {"source": "kline-unit", "warnings": ["kline_missing"]},
            "financial": {"source": "financial-unit", "warnings": []},
            "news": {"source": "news-unit", "warnings": []},
        },
    }


class AIAnalysisFallbackTests(unittest.TestCase):
    def test_risk_lights_escalate_data_and_cashflow_risks(self) -> None:
        lights = ai_analysis_fallbacks.build_risk_lights(_risky_stock_data())

        self.assertEqual(lights["data"]["level"], "red")
        self.assertEqual(lights["valuation"]["level"], "yellow")
        self.assertEqual(lights["financial"]["level"], "red")
        self.assertEqual(lights["news"]["level"], "yellow")
        self.assertEqual(lights["industry_events"]["level"], "yellow")
        self.assertEqual(lights["technical"]["level"], "yellow")

    def test_change_alerts_surface_price_announcement_sentiment_and_financial_context(self) -> None:
        alerts = ai_analysis_fallbacks.build_change_alerts(_risky_stock_data())

        alert_types = [item["type"] for item in alerts]
        self.assertEqual(alert_types, ["price", "announcement", "sentiment", "financial"])
        self.assertEqual(alerts[0]["level"], "high")
        self.assertLessEqual(len(alerts), 5)

    def test_batch_error_item_is_explicitly_unready_and_auditable(self) -> None:
        item = ai_analysis_fallbacks.build_batch_error_item(
            "600000.SH",
            report_mode="brief",
            audience="normal",
            error="source down",
        )

        self.assertEqual(item["symbol"], "600000.SH")
        self.assertEqual(item["model_status"], "error")
        self.assertFalse(item["readiness"]["ready"])
        self.assertIn("batch_item_failed", item["data_quality"]["quote"]["warnings"])
        self.assertEqual(item["change_alerts"][0]["type"], "error")

    def test_source_citation_keeps_structured_source_values_visible(self) -> None:
        stock_data = _risky_stock_data()
        stock_data["kline_data"] = [{"date": "2026-05-07", "close": 10.0}]
        citation = ai_analysis_fallbacks.build_source_citation("600000.SH", stock_data)

        for expected in ("quote-unit", "kline-unit", "financial-unit", "valuation-unit"):
            self.assertIn(expected, citation)

    def test_fallback_analysis_contains_symbol_error_and_source_citation(self) -> None:
        report = ai_analysis_fallbacks.build_fallback_analysis(
            "600000.SH",
            _risky_stock_data(),
            "model gateway timeout",
            audience="normal",
        )

        self.assertIn("600000.SH", report)
        self.assertIn("model gateway timeout", report)
        self.assertIn("quote-unit", report)


if __name__ == "__main__":
    unittest.main()
