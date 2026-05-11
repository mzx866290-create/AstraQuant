from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.evidence_chain import build_evidence_chain


class EvidenceChainTests(unittest.TestCase):
    def test_build_evidence_chain_maps_score_breakdown_to_structured_evidence(self) -> None:
        stock_data = {
            "price": 18.5,
            "quote": {"total_mv": 8_000_000_000, "pe_ttm": 20.0, "pb": 2.0},
            "financial": {"pe_ttm": 18.5, "pb": 1.9, "revenue_yoy": 12.0, "net_profit_yoy": 8.0},
            "data_quality": {
                "quote": {"source": "quote-source", "freshness": "realtime_or_latest", "confidence": "high"},
                "valuation": {"source": "financial_reports", "freshness": "latest_report", "confidence": "high"},
                "financial": {"source": "financial_reports", "freshness": "latest_report", "confidence": "high"},
                "kline": {"source": "kline-source", "freshness": "latest_trading_day", "confidence": "high"},
                "news": {"source": "news-source", "freshness": "recent_7d", "confidence": "medium"},
                "industry_events": {"source": "industry-source", "freshness": "recent_market_news", "confidence": "medium"},
            },
        }
        breakdown = [
            {"key": "valuation", "label": "估值", "delta": 10, "message": "PE 18.5，PB 1.9，估值字段可用"},
            {"key": "financial_profit", "label": "财务", "delta": 6, "message": "归母净利润同比为正：8.0%"},
        ]

        evidence = build_evidence_chain(stock_data, {}, {"id": "value_quality"}, breakdown)

        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]["factor"], "valuation")
        self.assertEqual(evidence[0]["dimension"], "valuation")
        self.assertEqual(evidence[0]["source"], "financial_reports")
        self.assertEqual(evidence[1]["threshold"], "net_profit_yoy > 0")


if __name__ == "__main__":
    unittest.main()
