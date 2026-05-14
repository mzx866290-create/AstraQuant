from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import date
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from backend.services.analysis_service.engine import recommendation_engine as engine


def _fake_module(name: str, **attrs) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


def _stock_row(symbol: str, name: str, market: str, sector: str = "") -> SimpleNamespace:
    return SimpleNamespace(symbol=symbol, name=name, market=market, sector=sector)


class _FakeColumn:
    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other):  # type: ignore[override]
        return ("eq", self.name, other)

    def asc(self):
        return ("asc", self.name)


class _FakeStock:
    id = _FakeColumn("id")
    is_active = _FakeColumn("is_active")
    market = _FakeColumn("market")


class _FakeQuery:
    def __init__(self, session) -> None:
        self._session = session
        self._market = None
        self._limit = None

    def filter(self, *clauses):
        for clause in clauses:
            if isinstance(clause, tuple) and clause[:2] == ("eq", "market"):
                self._market = clause[2]
        return self

    def order_by(self, *_clauses):
        return self

    def limit(self, size: int):
        self._limit = size
        return self

    def all(self):
        self._session.queried_markets.append(self._market)
        rows = list(self._session.rows_by_market.get(self._market, []))
        return rows[: self._limit]


class _FakeSession:
    def __init__(self, rows_by_market: dict[str, list[SimpleNamespace]]) -> None:
        self.rows_by_market = rows_by_market
        self.queried_markets: list[str] = []
        self.closed = False

    def query(self, _model):
        return _FakeQuery(self)

    def close(self) -> None:
        self.closed = True


def _stable_kline() -> list[dict]:
    closes = [38.0 + i * 0.08 for i in range(20)]
    return [{"close": close, "volume": 1000} for close in closes]


def _quality_stock_data() -> dict:
    return {
        "symbol": "000001.SZ",
        "name": "Unit Test Stock",
        "sector": "Quality",
        "price": 40.0,
        "change_pct": 1.25,
        "quote": {"pe_ttm": 21.0, "pb": 2.1, "total_mv": 8_000_000_000},
        "financial": {"pe_ttm": 18.5, "pb": 1.9, "total_mv": 8_000_000_000},
        "kline_data": _stable_kline(),
        "news_sentiment": {"weighted_dominant_sentiment": "neutral"},
        "industry_event_context": {
            "available": True,
            "themes": [
                {"theme": "theme-a"},
                {"theme": "theme-b"},
                {"theme": "theme-c"},
                {"theme": "theme-d"},
            ],
        },
        "readiness": {"data_grade": {"grade": "B", "source": "unit-fixture", "warnings": []}},
    }


def _install_candidate_db_modules(session: _FakeSession):
    return patch.dict(
        sys.modules,
        {
            "backend.shared.database": _fake_module(
                "backend.shared.database",
                SessionLocal=lambda: session,
            ),
            "backend.shared.models": _fake_module(
                "backend.shared.models",
                Stock=_FakeStock,
            ),
        },
    )


def _install_evaluation_modules(
    get_stock_data,
    enriched_stock_data: dict,
    build_risk_lights,
):
    context_builder = SimpleNamespace(enrich=Mock(return_value=enriched_stock_data))
    return (
        patch.dict(
            sys.modules,
            {
                "backend.services.analysis_service.engine.ai_analysis_data": _fake_module(
                    "backend.services.analysis_service.engine.ai_analysis_data",
                    get_stock_data=get_stock_data,
                ),
                "backend.services.analysis_service.engine.context_builder": _fake_module(
                    "backend.services.analysis_service.engine.context_builder",
                    context_builder=context_builder,
                ),
                "backend.services.analysis_service.engine.ai_analysis_fallbacks": _fake_module(
                    "backend.services.analysis_service.engine.ai_analysis_fallbacks",
                    build_risk_lights=build_risk_lights,
                ),
            },
        ),
        context_builder,
    )


class RecommendationEngineQualityTests(unittest.TestCase):
    def test_load_candidates_filters_duplicates_st_names_and_invalid_markets(self) -> None:
        session = _FakeSession(
            {
                "SH": [
                    _stock_row("600100", "Alpha", "SH", "tech"),
                    _stock_row("600100", "Duplicate Alpha", "SH", "tech"),
                    _stock_row("600200", "ST Risk", "SH", "risk"),
                    _stock_row("600300", "*ST Risk", "SH", "risk"),
                    _stock_row("700000", "Invalid Market", "BJ", "other"),
                ],
                "SZ": [
                    _stock_row("000001", "Beta", "SZ", "finance"),
                    _stock_row("000002", "", "SZ", "property"),
                ],
            }
        )

        with _install_candidate_db_modules(session):
            candidates = engine._load_recommendation_candidates("ALL", sample_size=5)

        self.assertCountEqual([item["symbol"] for item in candidates], ["600100.SH", "000001.SZ", "000002.SZ"])
        self.assertEqual({item["symbol"]: item["name"] for item in candidates}["000002.SZ"], "000002")
        self.assertEqual(session.queried_markets, ["SH", "SZ"])
        self.assertTrue(session.closed)

    def test_load_candidates_rotates_through_full_database_universe_by_day(self) -> None:
        session = _FakeSession(
            {
                "SH": [_stock_row(f"600{i:03d}", f"Alpha {i}", "SH", f"sector-{i % 5}") for i in range(30)],
                "SZ": [],
            }
        )

        with _install_candidate_db_modules(session):
            day_one = engine._load_recommendation_candidates("SH", sample_size=6, rotation_date=date(2026, 5, 9))
            day_two = engine._load_recommendation_candidates("SH", sample_size=6, rotation_date=date(2026, 5, 10))

        self.assertEqual(len(day_one), 6)
        self.assertEqual(len(day_two), 6)
        self.assertEqual(day_one[0]["_candidate_universe_count"], 30)
        self.assertEqual(day_one[0]["_candidate_rotation_date"], "2026-05-09")
        self.assertEqual(day_one[0]["_candidate_selection"], "daily_rotating_db_sample")
        self.assertNotEqual({item["symbol"] for item in day_one}, {item["symbol"] for item in day_two})

    def test_fallback_candidate_pool_honors_market_filter(self) -> None:
        all_candidates = engine._fallback_recommendation_candidates("ALL")
        sh_candidates = engine._fallback_recommendation_candidates("SH")
        sz_candidates = engine._fallback_recommendation_candidates("SZ")

        self.assertEqual(len(all_candidates), len(sh_candidates) + len(sz_candidates))
        self.assertTrue(all(item["market"] == "SH" and item["symbol"].endswith(".SH") for item in sh_candidates))
        self.assertTrue(all(item["market"] == "SZ" and item["symbol"].endswith(".SZ") for item in sz_candidates))

    def test_source_metadata_for_empty_and_fallback_results_is_explicit(self) -> None:
        empty = engine._empty_recommendations_result(
            market="ALL",
            strategy="retail_small",
            candidate_limit=20,
            concurrency=8,
            warnings=["candidate pool empty"],
        )

        self.assertEqual(empty["status"], "unavailable")
        self.assertEqual(empty["candidate_source"], "db")
        self.assertEqual(empty["data_grade"]["grade"], "D")
        self.assertEqual(empty["data_grade"]["source"], "db")

        marked = engine._mark_fallback_recommendation(
            {
                "symbol": "000001.SZ",
                "warnings": ["existing warning"],
                "data_grade": {"grade": "B", "warnings": ["grade warning"]},
            }
        )
        marked_again = engine._mark_fallback_recommendation(marked)

        self.assertEqual(marked_again["candidate_source"], "fallback")
        self.assertEqual(marked_again["source"], "fallback")
        self.assertEqual(marked_again["data_grade"]["candidate_source"], "fallback")
        self.assertEqual(marked_again["warnings"].count(engine._FALLBACK_CANDIDATE_WARNING), 1)
        self.assertEqual(marked_again["data_grade"]["warnings"].count(engine._FALLBACK_CANDIDATE_WARNING), 1)

    def test_score_penalizes_red_and_yellow_risk_lights_without_losing_reasons(self) -> None:
        stock_data = _quality_stock_data()

        clean_score, clean_reasons, _clean_flags = engine._score_daily_candidate(stock_data, {}, "retail_small")
        risky_score, risky_reasons, risk_flags = engine._score_daily_candidate(
            stock_data,
            {
                "governance": {"level": "red", "message": "unit red risk"},
                "liquidity": {"level": "yellow", "message": "unit yellow risk"},
            },
            "retail_small",
        )

        self.assertGreaterEqual(clean_score, 90)
        self.assertLess(risky_score, clean_score)
        self.assertGreaterEqual(risky_score, 55)
        self.assertIn("unit red risk", risk_flags)
        self.assertTrue(risky_reasons)
        self.assertEqual(clean_reasons[:2], risky_reasons[:2])

    def test_sentiment_positive_adds_score_and_negative_subtracts(self) -> None:
        base_data = _quality_stock_data()

        neutral_data = {**base_data, "news_sentiment": {"weighted_dominant_sentiment": "中性"}}
        positive_data = {**base_data, "news_sentiment": {"weighted_dominant_sentiment": "正面"}}
        negative_data = {**base_data, "news_sentiment": {"weighted_dominant_sentiment": "负面"}}

        neutral_score, _, _ = engine._score_daily_candidate(neutral_data, {}, "retail_small")
        positive_score, _, _ = engine._score_daily_candidate(positive_data, {}, "retail_small")
        negative_score, _, _ = engine._score_daily_candidate(negative_data, {}, "retail_small")

        self.assertGreater(positive_score, neutral_score, "positive sentiment must raise score above neutral")
        self.assertLess(negative_score, neutral_score, "negative sentiment must lower score below neutral")

    def test_score_breakdown_marks_sparse_data_and_risk_boundaries(self) -> None:
        sparse_stock_data = {
            "price": 0,
            "quote": {},
            "financial": {},
            "kline_data": [],
            "news_sentiment": {},
            "industry_event_context": {},
            "readiness": {"data_grade": {"grade": "C", "source": "unit-fixture"}},
        }

        breakdown = engine._build_score_breakdown(
            sparse_stock_data,
            {
                "audit": {"level": "red", "message": "red stop"},
                "liquidity": {"level": "yellow", "message": "yellow watch"},
            },
            "retail_small",
        )
        by_key = {item["key"]: item for item in breakdown}

        self.assertEqual(by_key["retail_affordability"]["delta"], -25)
        self.assertEqual(by_key["market_cap"]["delta"], -3)
        self.assertEqual(by_key["data_quality"]["delta"], 2)
        self.assertEqual(by_key["data_quality"]["status"], "warning")
        self.assertEqual(by_key["technical"]["status"], "warning")
        self.assertEqual(by_key["valuation"]["delta"], -4)
        self.assertEqual(by_key["financial"]["delta"], -5)
        self.assertEqual(by_key["risk_audit"]["delta"], -18)
        self.assertEqual(by_key["risk_liquidity"]["delta"], -2)
        self.assertEqual(by_key["risk_liquidity"]["status"], "warning")

    def test_evaluate_daily_candidate_returns_none_for_grade_d_before_risk_scoring(self) -> None:
        get_stock_data = AsyncMock(return_value={"symbol": "000001.SZ", "price": 12.0})
        build_risk_lights = Mock(return_value={"unused": {"level": "red"}})
        enriched = {"readiness": {"data_grade": {"grade": "D", "source": "unit-fixture"}}}
        module_patch, context_builder = _install_evaluation_modules(get_stock_data, enriched, build_risk_lights)

        with module_patch:
            result = asyncio.run(engine._evaluate_daily_candidate({"symbol": "000001.SZ"}, "retail_small"))

        self.assertIsNone(result)
        get_stock_data.assert_awaited_once_with("000001.SZ", include_news=True, include_profile=False)
        context_builder.enrich.assert_called_once_with(
            {"symbol": "000001.SZ", "price": 12.0},
            models_count=1,
            quota_ready=True,
            quota_message="",
        )
        build_risk_lights.assert_not_called()

    def test_evaluate_daily_candidate_uses_mocked_sources_for_successful_result(self) -> None:
        get_stock_data = AsyncMock(return_value={"symbol": "000001.SZ"})
        build_risk_lights = Mock(return_value={})
        module_patch, _context_builder = _install_evaluation_modules(
            get_stock_data,
            _quality_stock_data(),
            build_risk_lights,
        )

        with module_patch:
            result = asyncio.run(
                engine._evaluate_daily_candidate(
                    {"symbol": "000001.SZ", "name": "Pool Name", "market": "SZ", "sector": "Pool Sector"},
                    "retail_small",
                )
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["symbol"], "000001.SZ")
        self.assertEqual(result["name"], "Unit Test Stock")
        self.assertEqual(result["market"], "SZ")
        self.assertEqual(result["lot_cost"], 4000.0)
        self.assertEqual(result["pe_ttm"], 18.5)
        self.assertEqual(result["data_grade"]["source"], "unit-fixture")
        self.assertEqual(result["industry_themes"], ["theme-a", "theme-b", "theme-c"])
        self.assertTrue(result["score_breakdown"])
        self.assertGreaterEqual(result["score"], 55)

    def test_evaluate_daily_candidate_downgrades_source_exceptions_to_none(self) -> None:
        get_stock_data = AsyncMock(side_effect=RuntimeError("source failed"))
        build_risk_lights = Mock(return_value={})
        module_patch, context_builder = _install_evaluation_modules(get_stock_data, {}, build_risk_lights)

        with module_patch:
            result = asyncio.run(engine._evaluate_daily_candidate({"symbol": "000001.SZ"}, "retail_small"))

        self.assertIsNone(result)
        get_stock_data.assert_awaited_once()
        context_builder.enrich.assert_not_called()
        build_risk_lights.assert_not_called()

    def test_parallel_evaluation_drops_none_exceptions_and_timeouts(self) -> None:
        async def fake_evaluate(row: dict, _strategy: str):
            if row["symbol"] == "slow":
                await asyncio.sleep(0.05)
                return {"symbol": "slow"}
            if row["symbol"] == "none":
                return None
            if row["symbol"] == "boom":
                raise RuntimeError("candidate failed")
            return {"symbol": row["symbol"], "score": 70}

        with patch.object(engine, "_evaluate_daily_candidate", fake_evaluate):
            results = asyncio.run(
                engine._evaluate_candidates_parallel(
                    [{"symbol": "good"}, {"symbol": "none"}, {"symbol": "boom"}, {"symbol": "slow"}],
                    "retail_small",
                    concurrency=4,
                    timeout_seconds=0.001,
                )
            )

        self.assertEqual(results, [{"symbol": "good", "score": 70}])

    def test_number_guards_reject_zero_and_non_finite_values(self) -> None:
        self.assertTrue(engine.is_valid_score_number("12.5"))
        self.assertFalse(engine.is_valid_score_number(0))
        self.assertFalse(engine.is_valid_score_number(float("nan")))
        self.assertFalse(engine.is_valid_score_number(float("inf")))
        self.assertEqual(engine._valid_mv("300000000"), 300000000.0)
        self.assertIsNone(engine._valid_mv(0))
        self.assertIsNone(engine._valid_mv(float("nan")))


if __name__ == "__main__":
    unittest.main()
