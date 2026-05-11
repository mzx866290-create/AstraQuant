from __future__ import annotations

import unittest

from backend.services.analysis_service.engine.debate_engine import build_debate_view


class DebateEngineTests(unittest.TestCase):
    def test_build_debate_view_generates_bull_bear_and_falsification(self) -> None:
        evidence_chain = [
            {"factor": "valuation", "label": "估值", "impact": 10, "explanation": "估值字段可用"},
            {"factor": "financial_profit", "label": "财务", "impact": 6, "explanation": "利润同比为正"},
            {"factor": "risk_news", "label": "风险灯", "impact": -8, "explanation": "消息面偏负面"},
        ]
        stock_data = {
            "price": 18.5,
            "financial": {"net_profit_yoy": 8.0},
        }
        veto_result = {"passed": True, "warnings": [{"detail": "经营现金流为负"}]}

        debate = build_debate_view(stock_data, evidence_chain, veto_result, {"id": "value_quality", "name": "价值质量"})

        self.assertTrue(debate["bull_case"])
        self.assertTrue(debate["bear_case"])
        self.assertTrue(debate["falsification"])


if __name__ == "__main__":
    unittest.main()
