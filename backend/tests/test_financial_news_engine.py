from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from backend.services.analysis_service.engine.financial_engine import FinancialAnalysisEngine
from backend.services.analysis_service.engine.news_sentiment import NewsSentimentEngine


POSITIVE = "\u6b63\u9762"
NEGATIVE = "\u8d1f\u9762"
NEUTRAL = "\u4e2d\u6027"
HIGH = "\u9ad8"
LOW = "\u4f4e"


def _strong_reports() -> list[dict]:
    return [
        {
            "report_date": "2026-03-31",
            "report_type": "Q1",
            "roa": 6,
            "operating_cf": 150,
            "net_profit": 100,
            "total_liabilities": 300,
            "total_assets": 1000,
            "current_assets": 400,
            "current_liabilities": 200,
            "gross_margin": 35,
            "revenue": 500,
            "total_equity": 700,
            "net_margin": 20,
            "source": "akshare",
        },
        {
            "roa": 4,
            "operating_cf": 90,
            "net_profit": 120,
            "total_liabilities": 500,
            "total_assets": 1000,
            "current_assets": 300,
            "current_liabilities": 200,
            "gross_margin": 30,
            "revenue": 400,
            "total_equity": 500,
            "net_margin": 10,
        },
    ]


def _weak_reports() -> list[dict]:
    return [
        {
            "report_date": "2026-03-31",
            "roa": -2,
            "operating_cf": -50,
            "net_profit": 20,
            "total_liabilities": 900,
            "total_assets": 1000,
            "current_assets": 100,
            "current_liabilities": 300,
            "gross_margin": 18,
            "revenue": 120,
            "total_equity": 100,
        },
        {
            "roa": 3,
            "operating_cf": 100,
            "net_profit": 50,
            "total_liabilities": 600,
            "total_assets": 1000,
            "current_assets": 200,
            "current_liabilities": 300,
            "gross_margin": 22,
            "revenue": 200,
            "total_equity": 400,
        },
    ]


class FinancialAnalysisEngineTests(unittest.TestCase):
    def test_dupont_from_reports_normalizes_percent_margin_and_derives_drivers(self) -> None:
        result = FinancialAnalysisEngine.dupont_from_reports(_strong_reports())

        self.assertEqual(result["roe"], 0.14)
        self.assertEqual(result["net_margin"], 0.2)
        self.assertEqual(result["asset_turnover"], 0.5)
        self.assertEqual(result["equity_multiplier"], 1.4286)
        self.assertIn("\u9ad8\u5229\u6da6\u7387", result["interpretation"])
        self.assertIn("\u4f4e\u6760\u6746", result["interpretation"])

    def test_dupont_returns_incomplete_interpretation_when_inputs_are_missing(self) -> None:
        result = FinancialAnalysisEngine.dupont_from_reports([])

        self.assertIsNone(result["roe"])
        self.assertIsNone(result["net_margin"])
        self.assertIn("\u65e0\u6570\u636e", result["interpretation"])

    def test_piotroski_f_score_covers_strong_and_weak_fundamentals(self) -> None:
        strong = FinancialAnalysisEngine.piotroski_f_score(_strong_reports())
        weak = FinancialAnalysisEngine.piotroski_f_score(_weak_reports())

        self.assertEqual(strong["score"], 9)
        self.assertEqual(strong["max_score"], 9)
        self.assertTrue(all(item["passed"] for item in strong["details"]))
        self.assertIn("\u4f18\u79c0", strong["rating"])

        self.assertEqual(weak["score"], 1)
        self.assertEqual([item["score"] for item in weak["details"]].count(1), 1)
        self.assertIn("\u6781\u5dee", weak["rating"])

    def test_piotroski_requires_two_reports(self) -> None:
        result = FinancialAnalysisEngine.piotroski_f_score(_strong_reports()[:1])

        self.assertEqual(result["score"], 0)
        self.assertEqual(result["max_score"], 9)
        self.assertIn("\u6570\u636e\u4e0d\u8db3", result["rating"])

    def test_altman_z_score_handles_missing_assets_and_rating_bands(self) -> None:
        missing = FinancialAnalysisEngine.altman_z_score({"total_assets": 0})
        safe = FinancialAnalysisEngine.altman_z_score(_strong_reports()[0], market_cap=2000)
        danger = FinancialAnalysisEngine.altman_z_score(_weak_reports()[0], market_cap=50)

        self.assertIsNone(missing["z_score"])
        self.assertEqual(missing["components"], {})
        self.assertEqual(safe["z_score"], 6.05)
        self.assertIn("\u5b89\u5168\u533a", safe["rating"])
        self.assertLess(danger["z_score"], 1.81)
        self.assertIn("\u5371\u9669\u533a", danger["rating"])

    def test_pe_pb_band_reports_data_gaps_and_current_percentile_positions(self) -> None:
        result = FinancialAnalysisEngine.pe_pb_band(
            historical_pes=list(range(1, 21)),
            historical_pbs=[1, 2, 3],
            current_pe=5,
            current_pb=2,
        )

        self.assertEqual(result["pe_band"]["min"], 1)
        self.assertEqual(result["pe_band"]["median"], 11)
        self.assertEqual(result["pe_band"]["current"], 5)
        self.assertEqual(result["pe_band"]["percentile"], 25.0)
        self.assertIn("\u504f\u4f4e\u533a\u95f4", result["pe_band"]["position"])
        self.assertEqual(result["pb_band"]["error"], "\u5386\u53f2\u6570\u636e\u4e0d\u8db3")

    def test_financial_health_summary_combines_models_and_marks_source_quality(self) -> None:
        summary = FinancialAnalysisEngine.financial_health_summary(_strong_reports())
        no_data = FinancialAnalysisEngine.financial_health_summary([])

        self.assertEqual(summary["latest_report_date"], "2026-03-31")
        self.assertEqual(summary["debt_ratio"], 30.0)
        self.assertEqual(summary["f_score"]["score"], 9)
        self.assertIsNotNone(summary["z_score"]["z_score"])
        self.assertEqual(summary["data_quality"], "real")
        self.assertEqual(no_data["status"], "no_data")


class NewsSentimentEngineTests(unittest.TestCase):
    def test_match_benchmark_and_predict_impact_use_historical_event_baseline(self) -> None:
        title = "\u4e1a\u7ee9\u9884\u589e\u516c\u544a"

        benchmark = NewsSentimentEngine.match_benchmark(title)
        prediction = NewsSentimentEngine.predict_impact(
            title=title,
            sentiment_score=0.8,
            source_name="\u8bc1\u76d1\u4f1a",
        )

        self.assertIsNotNone(benchmark)
        self.assertEqual(prediction["direction"], POSITIVE)
        self.assertEqual(prediction["impact_1d_pct"], 2.5)
        self.assertEqual(prediction["impact_20d_pct"], 6.0)
        self.assertEqual(prediction["confidence"], 90.0)
        self.assertTrue(prediction["has_benchmark"])
        self.assertEqual(prediction["source_authority"], 1.0)
        self.assertEqual(prediction["note"], "")

    def test_predict_impact_falls_back_to_sentiment_when_no_benchmark_matches(self) -> None:
        prediction = NewsSentimentEngine.predict_impact(
            title="unit event without known benchmark",
            sentiment_score=-0.4,
            source_name="unit-source",
        )

        self.assertEqual(prediction["direction"], NEGATIVE)
        self.assertFalse(prediction["has_benchmark"])
        self.assertEqual(prediction["source_authority"], 0.3)
        self.assertEqual(prediction["impact_1d_pct"], -0.78)
        self.assertIn("\u60c5\u611f\u5f97\u5206", prediction["note"])

    def test_compute_influence_score_applies_authority_impact_and_freshness_weights(self) -> None:
        fresh_high = NewsSentimentEngine.compute_influence_score(
            sentiment_score=0.8,
            impact_level=HIGH,
            source_name="\u8bc1\u76d1\u4f1a",
            freshness_hours=0.5,
        )
        stale_low = NewsSentimentEngine.compute_influence_score(
            sentiment_score=-0.8,
            impact_level=LOW,
            source_name="unit-source",
            freshness_hours=96,
        )

        self.assertEqual(fresh_high, 7.0)
        self.assertEqual(stale_low, 0.2)

    def test_summarize_sentiment_returns_empty_and_stale_boundaries(self) -> None:
        empty = NewsSentimentEngine.summarize_sentiment([])
        stale = NewsSentimentEngine.summarize_sentiment(
            [
                {
                    "title": "old",
                    "sentiment": POSITIVE,
                    "sentiment_score": 0.9,
                    "publish_time": (datetime.now() - timedelta(days=10)).isoformat(),
                }
            ],
            days=7,
        )

        self.assertEqual(empty["total"], 0)
        self.assertEqual(empty["dominant_sentiment"], "\u65e0\u6570\u636e")
        self.assertEqual(stale["total"], 0)
        self.assertIn("7", stale["dominant_sentiment"])

    def test_summarize_sentiment_uses_weighted_impact_when_count_majority_is_less_relevant(self) -> None:
        now = datetime.now()
        news = [
            {
                "title": "small positive",
                "sentiment": POSITIVE,
                "sentiment_score": 0.4,
                "impact_level": LOW,
                "publish_time": (now - timedelta(hours=2)).isoformat(),
            },
            {
                "title": "large negative",
                "sentiment": NEGATIVE,
                "sentiment_score": 0.9,
                "impact_level": HIGH,
                "publish_time": (now - timedelta(hours=3)).isoformat(),
            },
            {
                "title": "older positive",
                "sentiment": POSITIVE,
                "sentiment_score": 0.2,
                "impact_level": LOW,
                "publish_time": (now - timedelta(days=2)).isoformat(),
            },
        ]

        summary = NewsSentimentEngine.summarize_sentiment(news, days=7)

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["positive"], 2)
        self.assertEqual(summary["negative"], 1)
        self.assertEqual(summary["positive_ratio"], 66.7)
        self.assertEqual(summary["avg_score"], 0.5)
        self.assertEqual(summary["count_dominant_sentiment"], POSITIVE)
        self.assertEqual(summary["weighted_dominant_sentiment"], NEGATIVE)
        self.assertEqual(summary["dominant_sentiment"], NEGATIVE)
        self.assertEqual(summary["dominant_basis"], "weighted_impact")
        self.assertEqual(summary["top_impact"][0]["title"], "large negative")
        self.assertNotIn("_parsed_time", summary["top_impact"][0])
        self.assertIn("\u6309\u5f71\u54cd\u529b\u52a0\u6743", summary["validation_note"])

    def test_summarize_sentiment_treats_invalid_publish_time_as_current_context(self) -> None:
        summary = NewsSentimentEngine.summarize_sentiment(
            [{"title": "invalid time", "sentiment": NEUTRAL, "sentiment_score": 0.0, "publish_time": "not-a-date"}],
            days=1,
        )

        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["neutral"], 1)
        self.assertEqual(summary["dominant_sentiment"], NEUTRAL)


if __name__ == "__main__":
    unittest.main()
