from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.context_builder import ContextBuilder


def _kline(days: int = 20) -> list[dict]:
    return [
        {
            "date": f"2026-04-{day:02d}",
            "open": 10.0 + day * 0.1,
            "high": 10.5 + day * 0.1,
            "low": 9.8 + day * 0.1,
            "close": 10.2 + day * 0.1,
            "volume": 1000 + day,
        }
        for day in range(1, days + 1)
    ]


def _complete_stock_data() -> dict:
    return {
        "symbol": "600519.SH",
        "name": "Unit Complete",
        "sector": "Food",
        "price": 1688.0,
        "change_pct": 1.2,
        "quote_source": "eastmoney",
        "kline_source": "clickhouse-primary",
        "quote": {
            "source": "eastmoney",
            "timestamp": "2026-05-07T09:30:00+00:00",
            "open": 1660.0,
            "high": 1699.0,
            "low": 1650.0,
            "volume": 123456,
            "turnover": 4567890,
            "pe_ttm": 25.1,
            "pb": 8.2,
        },
        "kline_data": _kline(20),
        "financial": {
            "source": "report-db",
            "valuation_source": "report-db",
            "report_date": "2026-03-31",
            "revenue": 100_000_000,
            "net_profit": 25_000_000,
            "operating_cf": 20_000_000,
            "pe_ttm": 24.8,
            "pb": 8.0,
        },
        "announcements": [{"announce_date": "2026-05-01", "title": "Annual report"}],
        "news": [{"publish_time": "2026-05-06T10:00:00+00:00", "title": "Product launch"}],
        "news_sentiment": {"total": 2, "positive": 1, "negative": 0},
        "industry_event_context": {
            "available": True,
            "note": "industry context ready",
            "themes": [
                {
                    "theme": "consumption",
                    "evidence": [{"publish_time": "2026-05-06T08:00:00+00:00"}],
                }
            ],
        },
        "crawl_status": {
            "quote": {
                "status": "success",
                "source": "eastmoney",
                "fetched": 1,
                "saved": 1,
                "finished_at": "2026-05-07T09:31:00+00:00",
            }
        },
        "source_attribution": {"verified": True, "warnings": []},
        "technical": {"trend": "up", "ma5": 1680.0},
        "money_flow_context": {
            "status": "ok",
            "source": "eastmoney",
            "warnings": [],
            "data_quality": {"confidence": 0.8},
        },
        "recommendation": {"label": "watch", "score": 78},
        "warnings": ["upstream_non_blocking_warning"],
    }


class ContextBuilderQualityTests(unittest.TestCase):
    def test_enrich_complete_context_marks_grade_a_and_preserves_context_sections(self) -> None:
        source = _complete_stock_data()

        enriched = ContextBuilder().enrich(source, models_count=2, quota_ready=True)

        self.assertIsNot(enriched, source)
        self.assertNotIn("data_quality", source)
        self.assertNotIn("readiness", source)
        for key in (
            "crawl_status",
            "source_attribution",
            "technical",
            "money_flow_context",
            "recommendation",
            "warnings",
        ):
            self.assertEqual(enriched[key], source[key])

        readiness = enriched["readiness"]
        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["blocking"], [])
        self.assertEqual(readiness["missing_context"], [])
        self.assertEqual(readiness["quality"], "complete")
        self.assertEqual(readiness["data_grade"]["grade"], "A")
        self.assertTrue(readiness["data_grade"]["has_quote"])
        self.assertTrue(readiness["data_grade"]["has_kline"])
        self.assertTrue(readiness["data_grade"]["has_financial"])
        self.assertTrue(readiness["data_grade"]["has_news"])
        self.assertTrue(readiness["data_grade"]["has_valuation"])

        quality = enriched["data_quality"]
        self.assertEqual(quality["quote"]["source"], "eastmoney")
        self.assertEqual(quality["quote"]["updated_at"], "2026-05-07T09:30:00+00:00")
        self.assertEqual(quality["quote"]["confidence"], "high")
        self.assertEqual(quality["quote"]["warnings"], [])
        self.assertEqual(quality["kline"]["source"], "clickhouse-primary")
        self.assertEqual(quality["kline"]["updated_at"], "2026-04-20")
        self.assertEqual(quality["kline"]["confidence"], "high")
        self.assertEqual(quality["financial"]["source"], "report-db")
        self.assertEqual(quality["financial"]["updated_at"], "2026-03-31")
        self.assertEqual(quality["news"]["source"], "news/db")
        self.assertEqual(quality["industry_events"]["source"], "news/db/industry-rule-engine")

    def test_enrich_model_and_quota_blockers_are_isolated_from_data_completeness(self) -> None:
        enriched = ContextBuilder().enrich(
            _complete_stock_data(),
            models_count=0,
            quota_ready=False,
            quota_message="daily quota exhausted",
        )

        readiness = enriched["readiness"]
        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["blocking"], ["ai_model", "quota"])
        self.assertEqual(readiness["missing_context"], [])
        self.assertEqual(readiness["quality"], "complete")
        self.assertEqual(readiness["items"]["ai_model"]["count"], 0)
        self.assertEqual(readiness["items"]["ai_model"]["message"], "no active model")
        self.assertFalse(readiness["items"]["quota"]["ready"])
        self.assertEqual(readiness["items"]["quota"]["message"], "daily quota exhausted")

    def test_enrich_sparse_data_reports_missing_context_and_low_confidence_warnings(self) -> None:
        sparse = {
            "symbol": "000001.SZ",
            "name": "Sparse Unit",
            "price": 0,
            "quote": {},
            "kline_data": [],
            "financial": {},
            "announcements": [],
            "news": [],
            "industry_event_context": {},
        }

        enriched = ContextBuilder().enrich(sparse, models_count=1, quota_ready=True)
        readiness = enriched["readiness"]

        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["blocking"], [])
        self.assertEqual(readiness["quality"], "usable_with_gaps")
        self.assertEqual(
            readiness["missing_context"],
            ["quote", "kline", "valuation", "financial", "announcements", "news", "industry_events"],
        )
        self.assertEqual(readiness["data_grade"]["grade"], "D")
        self.assertFalse(readiness["items"]["quote"]["ready"])
        self.assertEqual(readiness["items"]["quote"]["message"], "latest price missing or zero")

        quality = enriched["data_quality"]
        self.assertIn("latest_price_missing_or_zero", quality["quote"]["warnings"])
        self.assertEqual(quality["quote"]["confidence"], "medium")
        self.assertEqual(quality["kline"]["warnings"], ["kline_missing"])
        self.assertEqual(quality["kline"]["freshness"], "missing")
        self.assertEqual(quality["valuation"]["warnings"], ["pe_ttm_missing", "pb_missing"])
        self.assertEqual(quality["financial"]["warnings"], ["financial_missing"])
        self.assertEqual(quality["announcements"]["warnings"], ["announcements_missing"])
        self.assertEqual(quality["news"]["warnings"], ["news_missing"])
        self.assertEqual(quality["industry_events"]["warnings"], ["industry_event_context_missing"])

    def test_enrich_flags_fallback_quote_secondary_kline_financial_and_news_warnings(self) -> None:
        fallback = {
            "symbol": "300001.SZ",
            "name": "Fallback Unit",
            "price": 12.5,
            "quote_source": "synthetic-from-kline",
            "kline_source": "sina-secondary",
            "quote": {
                "source": "synthetic-from-kline",
                "timestamp": "2026-05-07T10:00:00+00:00",
                "synthetic": True,
                "open": 12.0,
                "high": 12.8,
                "low": 11.9,
                "volume": 5000,
                "turnover": 62500,
                "pe_ttm": 31.5,
            },
            "kline_data": _kline(10),
            "financial": {
                "source": "akshare",
                "report_date": "2026-03-31",
                "revenue": None,
                "net_profit": 8_000_000,
                "operating_cf": None,
            },
            "announcements": [],
            "news": [{"publish_time": "2026-05-07T08:30:00+00:00", "title": "Unit news"}],
            "news_sentiment": {"total": 1, "validation_note": "headline_deduped"},
            "industry_event_context": {
                "available": False,
                "warnings": ["industry_engine_disabled"],
            },
        }

        enriched = ContextBuilder().enrich(fallback, models_count=1, quota_ready=True)
        readiness = enriched["readiness"]
        quality = enriched["data_quality"]

        self.assertEqual(readiness["data_grade"]["grade"], "B")
        self.assertTrue(readiness["items"]["quote"]["ready"])
        self.assertTrue(readiness["items"]["kline"]["ready"])
        self.assertFalse(readiness["items"]["valuation"]["ready"])
        self.assertTrue(readiness["items"]["sentiment"]["ready"])
        self.assertEqual(readiness["items"]["sentiment"]["message"], "headline_deduped")
        self.assertIn("valuation", readiness["missing_context"])
        self.assertIn("announcements", readiness["missing_context"])
        self.assertIn("industry_events", readiness["missing_context"])

        self.assertTrue(quality["quote"]["is_fallback"])
        self.assertEqual(quality["quote"]["source"], "synthetic-from-kline")
        self.assertIn("quote_from_kline_fallback", quality["quote"]["warnings"])
        self.assertTrue(quality["kline"]["is_fallback"])
        self.assertEqual(
            quality["kline"]["warnings"],
            ["kline_less_than_20_days", "kline_secondary_source_used"],
        )
        self.assertEqual(quality["valuation"]["source"], "synthetic-from-kline")
        self.assertEqual(quality["valuation"]["warnings"], ["pb_missing"])
        self.assertEqual(quality["financial"]["warnings"], ["revenue_missing", "operating_cf_missing"])
        self.assertIn("headline_deduped", quality["news"]["warnings"])
        self.assertEqual(quality["industry_events"]["warnings"], ["industry_engine_disabled"])

    def test_enrich_detects_abnormal_quote_fields_even_when_other_sources_exist(self) -> None:
        abnormal = _complete_stock_data()
        abnormal.update(
            {
                "name": "Abnormal Unit",
                "price": 22.0,
                "quote": {
                    "source": "eastmoney",
                    "timestamp": "2026-05-07T11:00:00+00:00",
                    "open": 0,
                    "high": 0,
                    "low": 0,
                    "volume": 0,
                    "turnover": 0,
                    "pe_ttm": 12.0,
                    "pb": 1.3,
                },
            }
        )

        enriched = ContextBuilder().enrich(abnormal, models_count=1, quota_ready=True)
        readiness = enriched["readiness"]
        quote_quality = enriched["data_quality"]["quote"]

        self.assertEqual(readiness["data_grade"]["grade"], "D")
        self.assertEqual(readiness["data_grade"]["quote_abnormal"], "quote_trade_fields_missing_or_zero")
        self.assertFalse(readiness["items"]["quote"]["ready"])
        self.assertEqual(readiness["items"]["quote"]["message"], "quote_trade_fields_missing_or_zero")
        self.assertIn("quote", readiness["missing_context"])
        self.assertNotIn("kline", readiness["missing_context"])
        self.assertIn("quote_trade_fields_missing_or_zero", quote_quality["warnings"])
        self.assertEqual(quote_quality["confidence"], "medium")

    def test_enrich_marks_quote_and_kline_only_data_as_grade_c(self) -> None:
        technical_only = {
            "symbol": "002001.SZ",
            "name": "Technical Only",
            "price": 9.8,
            "quote_source": "sina",
            "kline_source": "sina",
            "quote": {
                "source": "sina",
                "timestamp": "2026-05-07T10:15:00+00:00",
                "open": 9.6,
                "high": 9.9,
                "low": 9.5,
                "volume": 20000,
                "turnover": 196000,
            },
            "kline_data": _kline(20),
            "financial": {},
            "announcements": [],
            "news": [],
            "news_sentiment": {},
            "industry_event_context": {"available": False},
            "technical": {"ma_cross": "neutral"},
            "money_flow_context": {"status": "unavailable", "warnings": ["money_flow_empty"]},
        }

        enriched = ContextBuilder().enrich(technical_only, models_count=1, quota_ready=True)
        readiness = enriched["readiness"]

        self.assertEqual(readiness["data_grade"]["grade"], "C")
        self.assertTrue(readiness["data_grade"]["has_quote"])
        self.assertTrue(readiness["data_grade"]["has_kline"])
        self.assertFalse(readiness["data_grade"]["has_valuation"])
        self.assertEqual(readiness["items"]["quote"]["quality"]["warnings"], [])
        self.assertEqual(readiness["items"]["kline"]["quality"]["warnings"], [])
        self.assertEqual(readiness["items"]["valuation"]["quality"]["warnings"], ["pe_ttm_missing", "pb_missing"])
        self.assertEqual(enriched["technical"], technical_only["technical"])
        self.assertEqual(enriched["money_flow_context"], technical_only["money_flow_context"])


if __name__ == "__main__":
    unittest.main()
