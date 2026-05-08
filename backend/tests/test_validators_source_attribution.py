from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from backend.services.analysis_service.engine.source_attribution import SourceAttributionManager
from backend.shared.validators import StockDataValidator, validate_email, validate_stock_symbol


class StockDataValidatorTests(unittest.TestCase):
    def test_validate_ohlc_filters_rows_that_break_price_invariants(self) -> None:
        df = pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-01-02"), "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5},
                {"date": pd.Timestamp("2026-01-05"), "open": 10.0, "high": 9.8, "low": 9.0, "close": 10.2},
                {"date": pd.Timestamp("2026-01-06"), "open": 10.0, "high": 10.8, "low": 10.1, "close": 9.9},
            ]
        )

        cleaned, report = StockDataValidator.validate_ohlc(df)

        self.assertEqual(report["total"], 3)
        self.assertEqual(len(report["issues"]), 1)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned.iloc[0]["close"], 10.5)

    def test_validate_continuity_reports_missing_business_dates_only(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02", "2026-01-06"]),
                "close": [10.0, 10.5],
            }
        )

        _, report = StockDataValidator.validate_continuity(df)

        self.assertEqual(report["missing_dates"], ["2026-01-05"])

    def test_validate_price_range_reports_abnormal_move_without_helper_columns(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
                "close": [10.0, 10.5, 14.0],
            }
        )

        validated, report = StockDataValidator.validate_price_range(df, pct_threshold=0.2)

        self.assertEqual(len(report["issues"]), 1)
        self.assertNotIn("prev_close", validated.columns)
        self.assertNotIn("price_change_pct", validated.columns)

    def test_full_validate_combines_reports_after_dropping_invalid_ohlc(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-01-02"),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 1000,
                },
                {
                    "date": pd.Timestamp("2026-01-05"),
                    "open": 10.0,
                    "high": 9.0,
                    "low": 9.2,
                    "close": 9.5,
                    "volume": 0,
                },
            ]
        )

        cleaned, report = StockDataValidator().full_validate(df)

        self.assertEqual(len(cleaned), 1)
        self.assertEqual(report["clean_rows"], 1)
        self.assertEqual(report["ohlc"]["total"], 2)
        self.assertEqual(report["volume"]["issues"], [])

    def test_simple_string_validators_keep_documented_lenient_contract(self) -> None:
        self.assertTrue(validate_stock_symbol("000001.SZ"))
        self.assertFalse(validate_stock_symbol(""))
        self.assertFalse(validate_stock_symbol("X" * 21))

        self.assertTrue(validate_email("user@example.com"))
        self.assertFalse(validate_email("user.example.com"))
        self.assertFalse(validate_email(""))


class SourceAttributionManagerTests(unittest.TestCase):
    def test_compute_freshness_covers_expected_age_buckets(self) -> None:
        now = datetime.now()

        self.assertEqual(SourceAttributionManager._compute_freshness(now - timedelta(minutes=1)), "realtime")
        self.assertEqual(SourceAttributionManager._compute_freshness(now - timedelta(hours=1)), "today")
        self.assertEqual(SourceAttributionManager._compute_freshness(now - timedelta(days=3)), "within_week")
        self.assertEqual(SourceAttributionManager._compute_freshness(now - timedelta(days=14)), "within_month")
        self.assertEqual(SourceAttributionManager._compute_freshness(now - timedelta(days=40)), "historical")

    def test_add_records_citation_metadata_and_historical_warning(self) -> None:
        manager = SourceAttributionManager()
        fetched_at = datetime.now(timezone.utc) - timedelta(days=40)

        manager.add("EastMoney", "financial_report", fetch_time=fetched_at, url="https://example.test", record_count=3)

        self.assertEqual(len(manager.citations), 1)
        citation = manager.citations[0]
        self.assertEqual(citation.source_name, "EastMoney")
        self.assertEqual(citation.data_type, "financial_report")
        self.assertEqual(citation.freshness, "historical")
        self.assertEqual(citation.url, "https://example.test")
        self.assertEqual(citation.record_count, 3)
        self.assertEqual(len(manager.warnings), 1)

    def test_citation_block_deduplicates_source_data_pairs_and_includes_warning(self) -> None:
        manager = SourceAttributionManager()
        fetched_at = datetime.now() - timedelta(days=40)
        manager.add("ClickHouse", "kline", fetch_time=fetched_at, record_count=2)
        manager.add("ClickHouse", "kline", fetch_time=fetched_at, record_count=2)
        manager.add("AKShare", "news", fetch_time=datetime.now() - timedelta(hours=1))

        block = manager.build_citation_block()

        self.assertEqual(block.count("**kline**: ClickHouse"), 1)
        self.assertIn("**news**: AKShare", block)
        self.assertIn("historical", block)
        self.assertIn("2", block)

    def test_freshness_summary_handles_empty_fresh_and_historical_sets(self) -> None:
        empty = SourceAttributionManager()
        self.assertEqual(empty.build_freshness_summary(), "\u65e0\u6570\u636e")

        fresh = SourceAttributionManager()
        fresh.add("EastMoney", "quote", fetch_time=datetime.now() - timedelta(minutes=10))
        self.assertIn("24", fresh.build_freshness_summary())

        stale = SourceAttributionManager()
        stale.add("EastMoney", "financial_report", fetch_time=datetime.now() - timedelta(days=40))
        self.assertIn("\u8f83\u65e7", stale.build_freshness_summary())

    def test_validate_claim_reports_numeric_mismatch_with_high_severity(self) -> None:
        manager = SourceAttributionManager()

        result = manager.validate_claim("PE\u4e3a13\u500d\uff0cROE\u8fbe15%", {"pe_ttm": 10.0, "roe": 15.0})

        self.assertFalse(result["verified"])
        self.assertEqual(result["claims_checked"], 2)
        self.assertEqual(result["severity"], "high")
        self.assertEqual(len(result["warnings"]), 1)
        warning = result["warnings"][0]
        self.assertEqual(warning["key"], "pe_ttm")
        self.assertEqual(warning["ai_value"], 13.0)
        self.assertEqual(warning["actual_value"], 10.0)


if __name__ == "__main__":
    unittest.main()
