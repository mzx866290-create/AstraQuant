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
        db_rows = [
            {"symbol": f"000{i:03d}.SZ", "name": f"Unit Test {i}", "market": "SZ"}
            for i in range(1, 21)
        ]
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

    def test_development_small_db_candidate_pool_uses_mixed_source(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        cache = MemoryCache()
        env = {"APP_ENV": "development"}
        db_rows = [{"symbol": "000001.SZ", "name": "Unit Test Bank", "market": "SZ"}]
        fallback_rows = [
            {"symbol": "000001.SZ", "name": "Duplicate Bank", "market": "SZ"},
            {"symbol": "000002.SZ", "name": "Fallback A", "market": "SZ"},
            {"symbol": "600001.SH", "name": "Fallback B", "market": "SH"},
        ]
        captured_symbols: list[str] = []

        async def fake_evaluate(candidates, strategy, concurrency=16):
            captured_symbols.extend(row["symbol"] for row in candidates)
            return [
                _scored_candidate("000001.SZ"),
                _scored_candidate("000002.SZ"),
                _scored_candidate("600001.SH"),
            ]

        with patch.dict("os.environ", env, clear=False), patch(
            "backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)
        ), patch.object(scoring, "_load_recommendation_candidates", return_value=db_rows), patch.object(
            scoring, "_fallback_recommendation_candidates", return_value=fallback_rows
        ), patch.object(
            scoring, "_evaluate_candidates_parallel", fake_evaluate
        ):
            result = asyncio.run(scoring.get_recommendations(market="ALL", limit=5, max_candidates=20, force_refresh=True, strategy="retail_small", concurrency=16))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["candidate_source"], "mixed")
        self.assertTrue(result["warnings"])
        self.assertEqual(captured_symbols, ["000001.SZ", "000002.SZ", "600001.SH"])

        by_symbol = {item["symbol"]: item for item in result["recommendations"]}
        self.assertNotIn("candidate_source", by_symbol["000001.SZ"])
        self.assertEqual(by_symbol["000002.SZ"]["candidate_source"], "fallback")
        self.assertEqual(by_symbol["600001.SH"]["source"], "fallback")

    def test_production_small_db_candidate_pool_never_uses_fallback(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        cache = MemoryCache()
        env = {"APP_ENV": "production"}
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
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["warnings"])
        self.assertNotIn("candidate_source", result["recommendations"][0])
        fallback.assert_not_called()

    def test_full_observation_request_bootstraps_once_then_returns_to_rotation(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        cache = MemoryCache()
        env = {
            "APP_ENV": "development",
            "DAILY_RECOMMENDATIONS_INITIAL_FULL_SCAN": "true",
            "DAILY_RECOMMENDATIONS_INITIAL_FULL_SCAN_MAX": "5000",
        }
        db_rows = [{"symbol": "000001.SZ", "name": "Unit Test Bank", "market": "SZ"}]
        candidate_sizes: list[int] = []

        def fake_load(_market: str, sample_size: int):
            candidate_sizes.append(sample_size)
            return [dict(row) for row in db_rows]

        with patch.dict("os.environ", env, clear=False), patch(
            "backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)
        ), patch.object(scoring, "_load_recommendation_candidates", side_effect=fake_load), patch.object(
            scoring, "_evaluate_candidates_parallel", AsyncMock(return_value=[_scored_candidate()])
        ):
            first = asyncio.run(
                scoring.get_recommendations(
                    market="ALL",
                    limit=50,
                    max_candidates=200,
                    force_refresh=True,
                    strategy="retail_small",
                    concurrency=16,
                    initial_full_scan=True,
                )
            )
            second = asyncio.run(
                scoring.get_recommendations(
                    market="ALL",
                    limit=50,
                    max_candidates=200,
                    force_refresh=True,
                    strategy="retail_small",
                    concurrency=16,
                    initial_full_scan=True,
                )
            )

        self.assertEqual(candidate_sizes, [5000, 200])
        self.assertTrue(first["initial_full_scan"]["used"])
        self.assertEqual(first["selection"]["mode"], "initial_full_scan")
        self.assertFalse(second["initial_full_scan"]["used"])
        self.assertEqual(second["initial_full_scan"]["status"], "already_completed")

    def test_full_observation_page_load_does_not_block_on_initial_full_scan_by_default(self) -> None:
        from backend.services.analysis_service.api.v1 import scoring

        cache = MemoryCache()
        env = {
            "APP_ENV": "development",
            "DAILY_RECOMMENDATIONS_INITIAL_FULL_SCAN": "true",
            "DAILY_RECOMMENDATIONS_INITIAL_FULL_SCAN_MAX": "5000",
        }
        db_rows = [{"symbol": "000001.SZ", "name": "Unit Test Bank", "market": "SZ"}]
        candidate_sizes: list[int] = []

        def fake_load(_market: str, sample_size: int):
            candidate_sizes.append(sample_size)
            return [dict(row) for row in db_rows]

        with patch.dict("os.environ", env, clear=False), patch(
            "backend.shared.cache.get_cache_manager", AsyncMock(return_value=cache)
        ), patch.object(scoring, "_load_recommendation_candidates", side_effect=fake_load), patch.object(
            scoring, "_evaluate_candidates_parallel", AsyncMock(return_value=[_scored_candidate()])
        ):
            result = asyncio.run(
                scoring.get_recommendations(
                    market="ALL",
                    limit=50,
                    max_candidates=200,
                    force_refresh=True,
                    strategy="retail_small",
                    concurrency=16,
                )
            )

        self.assertEqual(candidate_sizes, [200])
        self.assertFalse(result["initial_full_scan"]["used"])
        self.assertEqual(result["initial_full_scan"]["status"], "not_requested")


if __name__ == "__main__":
    unittest.main()
