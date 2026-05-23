from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch


class ScoringRecommendationFlagTests(unittest.TestCase):
    @staticmethod
    def _pipeline_result() -> dict:
        return {
            "recommendations": [
                {
                    "symbol": "000001.SZ",
                    "score": 80,
                    "data_grade": {"grade": "A"},
                    "risk_flags": [],
                }
            ],
            "market": "ALL",
            "status": "ok",
            "candidate_source": "db",
            "warnings": [],
            "count": 1,
            "candidate_count": 1,
            "candidate_universe_count": 1,
            "scored_count": 1,
            "selection": {"mode": "daily_rotating_db_sample"},
            "market_regime": {"regime": "range_bound"},
            "active_strategy": {"id": "retail_small"},
            "updated_at": "2026-05-09T00:00:00",
        }

    def test_recommendations_can_disable_evidence_and_debate_fields(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        with patch(
            "backend.services.analysis_service.api.v1.scoring.run_research_pipeline",
            AsyncMock(return_value=self._pipeline_result()),
        ) as run_pipeline, patch(
            "backend.shared.cache.get_cache_manager",
            AsyncMock(return_value=type("Cache", (), {"get": AsyncMock(return_value=None), "set": AsyncMock(return_value=None)})()),
        ):
            result = asyncio.run(
                scoring.get_recommendations(
                    market="ALL",
                    limit=5,
                    max_candidates=20,
                    force_refresh=True,
                    strategy="auto",
                    include_evidence=False,
                    include_debate=False,
                    concurrency=8,
                )
            )

        self.assertEqual(result["count"], 1)
        self.assertFalse(run_pipeline.await_args.kwargs["include_evidence"])
        self.assertFalse(run_pipeline.await_args.kwargs["include_debate"])

    def test_recommendation_cache_key_isolated_by_research_payload_flags(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        cache = type("Cache", (), {"get": AsyncMock(return_value=None), "set": AsyncMock(return_value=None)})()
        with patch(
            "backend.services.analysis_service.api.v1.scoring.run_research_pipeline",
            AsyncMock(return_value=self._pipeline_result()),
        ), patch("backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)):
            asyncio.run(
                scoring.get_recommendations(
                    market="ALL",
                    limit=5,
                    max_candidates=20,
                    force_refresh=False,
                    strategy="auto",
                    include_evidence=False,
                    include_debate=False,
                    concurrency=8,
                )
            )
            asyncio.run(
                scoring.get_recommendations(
                    market="ALL",
                    limit=5,
                    max_candidates=20,
                    force_refresh=False,
                    strategy="auto",
                    include_evidence=True,
                    include_debate=True,
                    concurrency=8,
                )
            )

        keys = [
            call.args[1]
            for call in cache.get.await_args_list
            if call.args[0] == "daily_recommendations" and "evidence-" in call.args[1]
        ]
        self.assertIn("evidence-0:debate-0", keys[0])
        self.assertIn("evidence-1:debate-1", keys[1])
        self.assertNotEqual(keys[0], keys[1])

    def test_lightweight_optimizer_can_use_internal_news_without_leaking_it(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        result = {
            "recommendations": [
                {
                    "symbol": "000001.SZ",
                    "score": 80,
                    "tier": "A",
                    "priority_score": 60,
                    "observation_action": "放量突破",
                    "evidence_chain": [],
                    "_news_impact_items": [
                        {
                            "factor": "news_impact_agent",
                            "direction": "positive",
                            "impact": 5,
                            "generated_at": "2026-05-22T08:00:00+00:00",
                            "value": {
                                "direction": "positive",
                                "relevance": "high",
                                "confidence": "high",
                                "summary": "unit news",
                            },
                        }
                    ],
                }
            ],
            "market_regime": {"regime": "range_bound"},
        }

        with patch(
            "backend.services.analysis_service.api.v1.scoring.fetch_review_feedback_for_symbols",
            return_value={},
        ):
            optimized = asyncio.run(scoring._ensure_observation_pool_optimizer(result))

        rec = optimized["recommendations"][0]
        self.assertEqual(optimized["pool_summary"]["optimizer"]["news_quality"]["with_news"], 1)
        self.assertEqual(rec["pool_optimizer"]["news"]["has_news"], True)
        self.assertEqual(rec["evidence_chain"], [])
        self.assertNotIn("_news_impact_items", rec)
        self.assertNotIn("_internal_evidence_chain_added", rec)


if __name__ == "__main__":
    unittest.main()
