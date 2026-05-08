from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch


class MemoryCache:
    def __init__(self) -> None:
        self.values = {}

    async def get(self, category: str, key: str):
        return self.values.get((category, key))

    async def set(self, category: str, key: str, value):
        self.values[(category, key)] = value


def _scored_candidate(symbol: str = "000001.SZ") -> dict:
    return {
        "symbol": symbol,
        "name": "Unit Test Bank",
        "market": "SZ",
        "sector": "Banking",
        "score": 80,
        "rating": {"label": "observe"},
        "reasons": ["unit-test"],
        "risk_flags": [],
        "data_grade": {"grade": "A", "source": "market-data"},
    }


class RecommendationCandidateSourceTests(unittest.TestCase):
    def test_production_empty_candidate_pool_returns_unavailable_without_fallback(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        cache = MemoryCache()
        env = {"APP_ENV": "production"}
        with patch.dict("os.environ", env, clear=False), patch(
            "backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)
        ), patch.object(scoring, "_load_recommendation_candidates", return_value=[]), patch.object(
            scoring, "_fallback_recommendation_candidates", return_value=[{"symbol": "000001.SZ"}]
        ) as fallback, patch.object(
            scoring, "_evaluate_candidates_parallel", AsyncMock(return_value=[])
        ) as evaluate:
            result = asyncio.run(scoring.get_recommendations(market="ALL", limit=5, max_candidates=20, force_refresh=True, strategy="retail_small", concurrency=16))

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["candidate_source"], "db")
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["count"], 0)
        self.assertTrue(result["warnings"])
        fallback.assert_not_called()
        evaluate.assert_not_called()

    def test_development_empty_candidate_pool_uses_marked_fallback(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        cache = MemoryCache()
        env = {"APP_ENV": "development"}
        fallback_rows = [{"symbol": "000001.SZ", "name": "Unit Test Bank", "market": "SZ"}]
        with patch.dict("os.environ", env, clear=False), patch(
            "backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)
        ), patch.object(scoring, "_load_recommendation_candidates", return_value=[]), patch.object(
            scoring, "_fallback_recommendation_candidates", return_value=fallback_rows
        ), patch.object(
            scoring, "_evaluate_candidates_parallel", AsyncMock(return_value=[_scored_candidate()])
        ):
            result = asyncio.run(scoring.get_recommendations(market="ALL", limit=5, max_candidates=20, force_refresh=True, strategy="retail_small", concurrency=16))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["candidate_source"], "fallback")
        self.assertTrue(result["warnings"])
        recommendation = result["recommendations"][0]
        self.assertEqual(recommendation["candidate_source"], "fallback")
        self.assertEqual(recommendation["source"], "fallback")
        self.assertTrue(recommendation["warnings"])
        self.assertEqual(recommendation["data_grade"]["candidate_source"], "fallback")
        self.assertTrue(recommendation["data_grade"]["warnings"])

    def test_db_candidate_pool_reports_db_source_without_warnings(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        cache = MemoryCache()
        env = {"APP_ENV": "development"}
        db_rows = [{"symbol": "000001.SZ", "name": "Unit Test Bank", "market": "SZ"}]
        with patch.dict("os.environ", env, clear=False), patch(
            "backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)
        ), patch.object(scoring, "_load_recommendation_candidates", return_value=db_rows), patch.object(
            scoring, "_fallback_recommendation_candidates"
        ) as fallback, patch.object(
            scoring, "_evaluate_candidates_parallel", AsyncMock(return_value=[_scored_candidate()])
        ):
            result = asyncio.run(scoring.get_recommendations(market="ALL", limit=5, max_candidates=20, force_refresh=True, strategy="retail_small", concurrency=16))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["candidate_source"], "db")
        self.assertEqual(result["warnings"], [])
        self.assertNotIn("candidate_source", result["recommendations"][0])
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
