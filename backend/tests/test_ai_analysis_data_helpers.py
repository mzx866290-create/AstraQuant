from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest

from backend.services.analysis_service.engine import ai_analysis_data


class AIAnalysisDataHelperTests(unittest.TestCase):
    def test_clean_symbol_strips_exchange_suffix(self) -> None:
        self.assertEqual(ai_analysis_data.clean_symbol("600519.SH"), "600519")
        self.assertEqual(ai_analysis_data.clean_symbol("ABC"), "ABC")

    def test_parse_profile_date_accepts_common_public_source_formats(self) -> None:
        self.assertEqual(ai_analysis_data.parse_profile_date("20200102"), "2020-01-02")
        self.assertEqual(ai_analysis_data.parse_profile_date("2020-03-04"), "2020-03-04")
        self.assertEqual(ai_analysis_data.parse_profile_date("2020/03/04"), "2020-03-04")
        self.assertEqual(ai_analysis_data.parse_profile_date("not-a-date-extra"), "not-a-date")
        self.assertIsNone(ai_analysis_data.parse_profile_date(None))

    def test_build_indicators_handles_empty_short_and_long_kline_windows(self) -> None:
        self.assertEqual(ai_analysis_data.build_indicators([]), {})

        rows = [{"close": idx} for idx in range(1, 21)]
        indicators = ai_analysis_data.build_indicators(rows)

        self.assertEqual(indicators["MA5"], 18.0)
        self.assertEqual(indicators["MA20"], 10.5)
        self.assertEqual(indicators["MA60"], "N/A")
        self.assertEqual(indicators["latest_price"], 20.0)

    def test_resolve_change_pct_prefers_quote_then_falls_back_to_kline(self) -> None:
        kline = [{"close": 100}, {"close": 110}]

        self.assertEqual(ai_analysis_data.resolve_change_pct({"change_pct": "3.456"}, kline, 110), 3.46)
        self.assertEqual(ai_analysis_data.resolve_change_pct({"change_pct": "bad"}, kline, 110), 10.0)
        self.assertEqual(ai_analysis_data.resolve_change_pct({}, [{"close": 0}, {"close": 110}], 110), 0.0)
        self.assertEqual(ai_analysis_data.resolve_change_pct({}, [{"close": 110}], 110), 0.0)

    def test_map_financial_fills_missing_valuation_from_quote_with_source(self) -> None:
        latest = SimpleNamespace(
            report_date=date(2026, 3, 31),
            report_type="Q1",
            revenue=10_000_000,
            revenue_yoy=1.2,
            net_profit=2_000_000,
            net_profit_yoy=2.3,
            gross_margin=30.1,
            net_margin=12.3,
            eps=0.5,
            bvps=3.2,
            roe=8.8,
            roa=4.4,
            total_assets=100_000_000,
            total_liabilities=40_000_000,
            total_equity=60_000_000,
            operating_cf=1_500_000,
            pe_ttm=None,
            pb=None,
            source="",
        )
        quote = {
            "pe_ttm": 12.3,
            "pb": 1.8,
            "total_mv": 12_000_000_000,
            "circ_mv": 10_000_000_000,
            "source": "quote-unit",
        }

        mapped = ai_analysis_data.map_financial(latest, quote)

        self.assertEqual(mapped["report_date"], "2026-03-31")
        self.assertEqual(mapped["source"], "akshare")
        self.assertEqual(mapped["pe_ttm"], 12.3)
        self.assertEqual(mapped["pb"], 1.8)
        self.assertEqual(mapped["total_mv"], 12_000_000_000)
        self.assertEqual(mapped["circ_mv"], 10_000_000_000)
        self.assertEqual(mapped["valuation_source"], "quote-unit")


if __name__ == "__main__":
    unittest.main()
