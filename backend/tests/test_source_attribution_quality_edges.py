from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.source_attribution import (
    SourceAttributionManager,
    SourceCitation,
)


class SourceAttributionQualityEdgeTests(unittest.TestCase):
    def test_empty_citation_block_uses_explicit_no_record_message(self) -> None:
        block = SourceAttributionManager().build_citation_block()

        self.assertIn("数据来源", block)
        self.assertIn("无记录", block)

    def test_citation_block_handles_unknown_freshness_and_missing_record_count(self) -> None:
        manager = SourceAttributionManager()
        manager.citations.append(
            SourceCitation(
                source_name="UnitSource",
                data_type="quote",
                fetch_time="2026-05-07T09:30:00",
                freshness="mystery",
                record_count=0,
            )
        )

        block = manager.build_citation_block()

        self.assertIn("UnitSource", block)
        self.assertIn("mystery", block)
        self.assertNotIn("0条", block)

    def test_freshness_summary_reports_recent_non_realtime_set_as_newer_data(self) -> None:
        manager = SourceAttributionManager()
        manager.citations.extend(
            [
                SourceCitation("ClickHouse", "kline", "2026-05-07T09:30:00", "within_week"),
                SourceCitation("EastMoney", "news", "2026-05-06T09:30:00", "within_month"),
            ]
        )

        self.assertIn("7天", manager.build_freshness_summary())

    def test_validate_claim_accepts_within_tolerance_and_reports_low_severity(self) -> None:
        manager = SourceAttributionManager()

        matched = manager.validate_claim(
            "PB为2.09倍，营收约101亿，净利润为20.8亿，毛利率达50.9%，净利率为18.4%，涨跌幅为-1.01%",
            {
                "pb": 2.0,
                "revenue": 100.0,
                "net_profit": 20.0,
                "gross_margin": 50.0,
                "net_margin": 18.0,
                "change_pct": -1.0,
            },
        )
        no_source_value = manager.validate_claim("PE为30倍", {})

        self.assertTrue(matched["verified"])
        self.assertEqual(matched["claims_checked"], 6)
        self.assertEqual(matched["severity"], "none")
        self.assertTrue(no_source_value["verified"])
        self.assertEqual(no_source_value["claims_checked"], 1)

        low = manager.validate_claim("毛利率为52%", {"gross_margin": 50.0})
        self.assertFalse(low["verified"])
        self.assertEqual(low["severity"], "low")


if __name__ == "__main__":
    unittest.main()
