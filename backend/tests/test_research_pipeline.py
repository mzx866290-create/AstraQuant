from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.analysis_service.engine.research_pipeline import run_research_pipeline


def _candidate(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "name": f"Unit {symbol}",
        "market": "SZ",
        "sector": "Tech",
        "_candidate_universe_count": 12,
        "_candidate_rotation_date": "2026-05-09",
        "_candidate_selection": "daily_rotating_db_sample",
    }


def _scored(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "name": f"Unit {symbol}",
        "market": "SZ",
        "sector": "Tech",
        "score": 76,
        "rating": {"level": "B", "text": "值得跟踪"},
        "reasons": ["unit"],
        "risk_flags": [],
        "risk_lights": {},
        "data_grade": {"grade": "B", "label": "可用"},
        "price": 18.0,
        "score_breakdown": [{"key": "industry_events", "label": "主题", "delta": 3, "message": "theme"}],
        "stock_data": {
            "symbol": symbol,
            "name": f"Unit {symbol}",
            "sector": "计算机",
            "price": 18.0,
            "readiness": {"data_grade": {"grade": "B"}},
            "quote": {},
            "financial": {"revenue_yoy": 10.0},
            "announcements": [{"title": "公司取得AI项目订单", "announce_date": "2026-05-08"}],
            "industry_event_context": {
                "themes": [
                    {
                        "theme": "AI算力与数字经济",
                        "confidence": "high",
                        "evidence": [{"title": "AI政策", "source": "unit"}],
                    }
                ]
            },
            "data_quality": {
                "industry_events": {"source": "unit", "freshness": "recent", "confidence": "medium"}
            },
        },
    }


def _scored_with_breakdown(symbol: str, score_breakdown: list[dict]) -> dict:
    item = _scored(symbol)
    item["score_breakdown"] = score_breakdown
    return item


class ResearchPipelineTests(unittest.TestCase):
    def test_pipeline_returns_market_regime_and_active_strategy_for_auto_mode(self) -> None:
        with patch(
            "backend.services.analysis_service.engine.research_pipeline.detect_market_regime",
            AsyncMock(return_value={
                "regime": "strong_trend",
                "confidence": "high",
                "signals": [],
                "suggested_strategies": ["growth_momentum"],
            }),
        ):
            result = asyncio.run(
                run_research_pipeline(
                    market="ALL",
                    limit=5,
                    requested_strategy="auto",
                    candidate_limit=20,
                    concurrency=8,
                    run_initial_full_scan=False,
                    load_candidates=lambda _market, _limit: [_candidate("000001.SZ")],
                    evaluate_candidates=AsyncMock(return_value=[_scored("000001.SZ")]),
                )
            )

        self.assertEqual(result["market_regime"]["regime"], "strong_trend")
        self.assertEqual(result["active_strategy"]["id"], "growth_momentum")
        self.assertEqual(result["recommendations"][0]["strategy_id"], "growth_momentum")
        self.assertIn("base_score", result["recommendations"][0])
        self.assertIn("strategy_score", result["recommendations"][0])
        self.assertIn("strategy_weighted_factors", result["recommendations"][0])
        self.assertEqual(result["recommendations"][0]["theme_validation"]["verification"]["level"], "verified")
        self.assertTrue(
            any(item.get("factor") == "theme_validation" for item in result["recommendations"][0]["evidence_chain"])
        )

    def test_pipeline_filters_hard_veto_candidates(self) -> None:
        vetoed = _scored("000001.SZ")
        vetoed["name"] = "ST Unit"
        vetoed["stock_data"]["name"] = "ST Unit"

        with patch(
            "backend.services.analysis_service.engine.research_pipeline.detect_market_regime",
            AsyncMock(return_value={
                "regime": "range_bound",
                "confidence": "medium",
                "signals": [],
                "suggested_strategies": ["retail_small"],
            }),
        ):
            result = asyncio.run(
                run_research_pipeline(
                    market="ALL",
                    limit=5,
                    requested_strategy="retail_small",
                    candidate_limit=20,
                    concurrency=8,
                    run_initial_full_scan=False,
                    load_candidates=lambda _market, _limit: [_candidate("000001.SZ")],
                    evaluate_candidates=AsyncMock(return_value=[vetoed]),
                )
            )

        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["count"], 0)

    def test_pipeline_sorts_by_strategy_weighted_score(self) -> None:
        technical = _scored_with_breakdown(
            "000001.SZ",
            [
                {"key": "base", "label": "base", "delta": 50},
                {"key": "technical", "label": "technical", "delta": 20},
                {"key": "valuation", "label": "valuation", "delta": -12},
            ],
        )
        value = _scored_with_breakdown(
            "000002.SZ",
            [
                {"key": "base", "label": "base", "delta": 50},
                {"key": "technical", "label": "technical", "delta": -8},
                {"key": "valuation", "label": "valuation", "delta": 20},
            ],
        )

        with patch(
            "backend.services.analysis_service.engine.research_pipeline.detect_market_regime",
            AsyncMock(return_value={
                "regime": "weak_market",
                "confidence": "high",
                "signals": [],
                "suggested_strategies": ["value_quality"],
            }),
        ):
            result = asyncio.run(
                run_research_pipeline(
                    market="ALL",
                    limit=2,
                    requested_strategy="value_quality",
                    candidate_limit=20,
                    concurrency=8,
                    run_initial_full_scan=False,
                    include_evidence=False,
                    include_debate=False,
                    load_candidates=lambda _market, _limit: [_candidate("000001.SZ"), _candidate("000002.SZ")],
                    evaluate_candidates=AsyncMock(return_value=[technical, value]),
                )
            )

        self.assertEqual([item["symbol"] for item in result["recommendations"]], ["000002.SZ", "000001.SZ"])
        self.assertEqual(result["recommendations"][0]["base_score"], 76)
        self.assertEqual(result["recommendations"][0]["score"], result["recommendations"][0]["strategy_score"])
        self.assertGreater(
            result["recommendations"][0]["strategy_score"],
            result["recommendations"][1]["strategy_score"],
        )

    def test_pipeline_applies_strategy_score_threshold_filter(self) -> None:
        low_score = _scored_with_breakdown(
            "000001.SZ",
            [
                {"key": "base", "label": "base", "delta": 50},
                {"key": "technical", "label": "technical", "delta": -30},
                {"key": "valuation", "label": "valuation", "delta": -20},
            ],
        )
        high_score = _scored_with_breakdown(
            "000002.SZ",
            [
                {"key": "base", "label": "base", "delta": 50},
                {"key": "technical", "label": "technical", "delta": 20},
                {"key": "valuation", "label": "valuation", "delta": 10},
            ],
        )

        with patch(
            "backend.services.analysis_service.engine.research_pipeline.detect_market_regime",
            AsyncMock(return_value={
                "regime": "weak_market",
                "confidence": "high",
                "signals": [],
                "suggested_strategies": ["dividend_defensive"],
            }),
        ):
            result = asyncio.run(
                run_research_pipeline(
                    market="ALL",
                    limit=2,
                    requested_strategy="dividend_defensive",
                    candidate_limit=20,
                    concurrency=8,
                    run_initial_full_scan=False,
                    include_evidence=False,
                    include_debate=False,
                    load_candidates=lambda _market, _limit: [_candidate("000001.SZ"), _candidate("000002.SZ")],
                    evaluate_candidates=AsyncMock(return_value=[low_score, high_score]),
                )
            )

        self.assertEqual([item["symbol"] for item in result["recommendations"]], ["000002.SZ"])
        self.assertIn("strategy_filter_result", result["recommendations"][0])


if __name__ == "__main__":
    unittest.main()
