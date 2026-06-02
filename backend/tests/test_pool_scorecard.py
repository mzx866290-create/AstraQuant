from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from backend.services.analysis_service.engine.review_tracker import (
    _build_scorecard_bucket,
    _discipline_exit_return,
    _find_nearest_close,
    _simulation_bucket,
    build_pool_scorecard,
    build_pool_simulation,
)


class FindNearestCloseTests(unittest.TestCase):
    def test_exact_match(self):
        date_map = {"2026-05-20": 3800.0, "2026-05-21": 3810.0}
        self.assertEqual(_find_nearest_close(date_map, "2026-05-20"), 3800.0)

    def test_nearest_within_tolerance(self):
        date_map = {"2026-05-19": 3790.0, "2026-05-21": 3810.0}
        result = _find_nearest_close(date_map, "2026-05-20")
        self.assertIn(result, [3790.0, 3810.0])

    def test_beyond_tolerance_returns_none(self):
        date_map = {"2026-05-10": 3700.0}
        self.assertIsNone(_find_nearest_close(date_map, "2026-05-20", tolerance=3))

    def test_invalid_date_returns_none(self):
        self.assertIsNone(_find_nearest_close({"2026-05-20": 100.0}, "not-a-date"))


class BuildScorecardBucketTests(unittest.TestCase):
    def test_below_threshold_returns_nulls(self):
        result = _build_scorecard_bucket([1.0, 2.0, -1.0], [0.5, 1.0, -0.5], [-2.0])
        self.assertEqual(result["reviews"], 3)
        self.assertIsNone(result["win_rate"])
        self.assertIsNone(result["avg_return_pct"])
        self.assertIsNone(result["avg_excess_pct"])

    def test_above_threshold_computes_stats(self):
        returns = [2.0, -1.0, 3.0, 1.5, -0.5, 4.0, 2.5, -2.0, 1.0, 0.5]
        excess = [1.0, -1.5, 2.0, 0.5, -1.0, 3.0, 1.5, -2.5, 0.0, -0.5]
        drawdowns = [-1.0, -3.0, -0.5, -2.0, -1.5, -0.8, -4.0, -1.2, -0.3, -2.5]
        result = _build_scorecard_bucket(returns, excess, drawdowns)

        self.assertEqual(result["reviews"], 10)
        self.assertEqual(result["win_rate"], 0.7)
        self.assertAlmostEqual(result["avg_return_pct"], 1.1, places=4)
        self.assertAlmostEqual(result["avg_excess_pct"], 0.25, places=4)
        self.assertEqual(result["worst_return_pct"], -2.0)
        self.assertEqual(result["max_drawdown_pct"], -4.0)

    def test_no_excess_data(self):
        returns = [1.0] * 12
        excess = [None] * 12
        result = _build_scorecard_bucket(returns, excess, [])
        self.assertEqual(result["win_rate"], 1.0)
        self.assertIsNone(result["avg_excess_pct"])
        self.assertIsNone(result["max_drawdown_pct"])


class BuildPoolScorecardTests(unittest.IsolatedAsyncioTestCase):
    async def test_tables_missing(self):
        with patch("backend.services.analysis_service.engine.review_tracker._has_table", return_value=False):
            result = await build_pool_scorecard()
        self.assertEqual(result["status"], "tables_missing")

    async def test_insufficient_data(self):
        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        with (
            patch("backend.services.analysis_service.engine.review_tracker._has_table", return_value=True),
            patch("backend.shared.cache.get_cache_manager", return_value=mock_cache),
            patch("backend.services.analysis_service.engine.scoring_data.fetch_recent_kline", new_callable=AsyncMock, return_value=[]),
            patch("backend.services.analysis_service.engine.review_tracker.SessionLocal") as mock_session_cls,
        ):
            mock_db = MagicMock()
            mock_session_cls.return_value = mock_db
            mock_query = MagicMock()
            mock_db.query.return_value = mock_query
            mock_query.join.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.all.return_value = []

            result = await build_pool_scorecard(lookback_days=30, strategy="auto")

        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["overall"], {})

    async def test_benchmark_unavailable_still_returns_absolute(self):
        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        snapshot_date = datetime(2026, 5, 1, tzinfo=timezone.utc)
        review_date = datetime(2026, 5, 6, tzinfo=timezone.utc)

        mock_observation = MagicMock()
        mock_observation.factor_snapshot_json = {"tier": "A"}
        mock_observation.snapshot_date = snapshot_date
        mock_observation.strategy_id = "retail_small"

        mock_review = MagicMock()
        mock_review.review_offset = "T+5"
        mock_review.return_pct = 3.5
        mock_review.max_drawdown_pct = -1.2
        mock_review.review_date = review_date

        rows = [(mock_observation, mock_review)] * 12

        with (
            patch("backend.services.analysis_service.engine.review_tracker._has_table", return_value=True),
            patch("backend.shared.cache.get_cache_manager", return_value=mock_cache),
            patch("backend.services.analysis_service.engine.scoring_data.fetch_recent_kline", new_callable=AsyncMock, side_effect=RuntimeError("network")),
            patch("backend.services.analysis_service.engine.review_tracker.SessionLocal") as mock_session_cls,
        ):
            mock_db = MagicMock()
            mock_session_cls.return_value = mock_db
            mock_query = MagicMock()
            mock_db.query.return_value = mock_query
            mock_query.join.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.all.return_value = rows

            result = await build_pool_scorecard(lookback_days=90, strategy="auto")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["benchmark_status"], "unavailable")
        a_t5 = result["by_tier"]["A"]["T+5"]
        self.assertEqual(a_t5["reviews"], 12)
        self.assertEqual(a_t5["win_rate"], 1.0)
        self.assertAlmostEqual(a_t5["avg_return_pct"], 3.5)
        self.assertIsNone(a_t5["avg_excess_pct"])

    async def test_normal_aggregation_with_benchmark(self):
        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        snapshot_date = datetime(2026, 5, 1, tzinfo=timezone.utc)
        review_date = datetime(2026, 5, 6, tzinfo=timezone.utc)

        mock_observation = MagicMock()
        mock_observation.factor_snapshot_json = {"tier": "A"}
        mock_observation.snapshot_date = snapshot_date
        mock_observation.strategy_id = "retail_small"

        mock_review = MagicMock()
        mock_review.review_offset = "T+5"
        mock_review.return_pct = 3.0
        mock_review.max_drawdown_pct = -1.0
        mock_review.review_date = review_date

        rows = [(mock_observation, mock_review)] * 15

        kline = [
            {"trade_date": "2026-05-01", "close": 3800.0},
            {"trade_date": "2026-05-06", "close": 3838.0},
        ]

        with (
            patch("backend.services.analysis_service.engine.review_tracker._has_table", return_value=True),
            patch("backend.shared.cache.get_cache_manager", return_value=mock_cache),
            patch("backend.services.analysis_service.engine.scoring_data.fetch_recent_kline", new_callable=AsyncMock, return_value=kline),
            patch("backend.services.analysis_service.engine.review_tracker.SessionLocal") as mock_session_cls,
        ):
            mock_db = MagicMock()
            mock_session_cls.return_value = mock_db
            mock_query = MagicMock()
            mock_db.query.return_value = mock_query
            mock_query.join.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.all.return_value = rows

            result = await build_pool_scorecard(lookback_days=90, strategy="auto")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["benchmark_status"], "ok")
        a_t5 = result["by_tier"]["A"]["T+5"]
        self.assertEqual(a_t5["reviews"], 15)
        self.assertEqual(a_t5["win_rate"], 1.0)
        self.assertAlmostEqual(a_t5["avg_return_pct"], 3.0)
        expected_bench = (3838.0 / 3800.0 - 1) * 100
        expected_excess = 3.0 - expected_bench
        self.assertAlmostEqual(a_t5["avg_excess_pct"], round(expected_excess, 4), places=3)


class DisciplineExitReturnTests(unittest.TestCase):
    def test_stops_out_when_drawdown_breaches_threshold(self):
        # Held to +3% but drew down to -15% along the way -> discipline stops at -10%.
        exit_return, stopped = _discipline_exit_return(3.0, -15.0)
        self.assertEqual(exit_return, -10.0)
        self.assertTrue(stopped)

    def test_holds_when_drawdown_within_threshold(self):
        exit_return, stopped = _discipline_exit_return(3.0, -4.0)
        self.assertEqual(exit_return, 3.0)
        self.assertFalse(stopped)

    def test_no_drawdown_data_holds_to_offset(self):
        exit_return, stopped = _discipline_exit_return(-2.0, None)
        self.assertEqual(exit_return, -2.0)
        self.assertFalse(stopped)


class SimulationBucketTests(unittest.TestCase):
    def test_below_threshold_returns_nulls(self):
        result = _simulation_bucket([1.0, -2.0, 3.0])
        self.assertEqual(result["trades"], 3)
        self.assertIsNone(result["win_rate"])
        self.assertIsNone(result["expectancy_pct"])
        self.assertIsNone(result["payoff_ratio"])

    def test_expectancy_and_payoff_ratio(self):
        # 6 wins of +5, 4 losses of -2.5: win_rate 0.6, expectancy = 0.6*5 + 0.4*(-2.5) = 2.0
        returns = [5.0] * 6 + [-2.5] * 4
        result = _simulation_bucket(returns)
        self.assertEqual(result["trades"], 10)
        self.assertEqual(result["win_rate"], 0.6)
        self.assertAlmostEqual(result["expectancy_pct"], 2.0, places=4)
        self.assertAlmostEqual(result["avg_win_pct"], 5.0, places=4)
        self.assertAlmostEqual(result["avg_loss_pct"], -2.5, places=4)
        self.assertAlmostEqual(result["payoff_ratio"], 2.0, places=4)

    def test_high_win_rate_can_still_be_negative_expectancy(self):
        # 9 small wins of +1, 1 big loss of -20: win_rate 0.9 but expectancy negative.
        returns = [1.0] * 9 + [-20.0]
        result = _simulation_bucket(returns)
        self.assertEqual(result["win_rate"], 0.9)
        self.assertLess(result["expectancy_pct"], 0)


class BuildPoolSimulationTests(unittest.TestCase):
    def test_tables_missing(self):
        with patch("backend.services.analysis_service.engine.review_tracker._has_table", return_value=False):
            result = build_pool_simulation()
        self.assertEqual(result["status"], "tables_missing")

    def test_insufficient_data(self):
        with (
            patch("backend.services.analysis_service.engine.review_tracker._has_table", return_value=True),
            patch("backend.services.analysis_service.engine.review_tracker.SessionLocal") as mock_session_cls,
        ):
            mock_db = MagicMock()
            mock_session_cls.return_value = mock_db
            mock_query = MagicMock()
            mock_db.query.return_value = mock_query
            mock_query.join.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.all.return_value = []
            result = build_pool_simulation(lookback_days=30, strategy="auto")
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["overall"], {})

    def test_discipline_beats_buy_hold_when_stops_cut_tails(self):
        snapshot_date = datetime(2026, 5, 1, tzinfo=timezone.utc)

        def _obs():
            obs = MagicMock()
            obs.factor_snapshot_json = {"tier": "A"}
            obs.snapshot_date = snapshot_date
            obs.strategy_id = "retail_small"
            return obs

        # 7 winners (+4%, no stop) and 5 deep losers (-25% return, -30% drawdown).
        # Buy&hold eats the full -25%; discipline caps each loser at -10%.
        rows = []
        for _ in range(7):
            r = MagicMock()
            r.review_offset = "T+5"
            r.return_pct = 4.0
            r.max_drawdown_pct = -2.0
            rows.append((_obs(), r))
        for _ in range(5):
            r = MagicMock()
            r.review_offset = "T+5"
            r.return_pct = -25.0
            r.max_drawdown_pct = -30.0
            rows.append((_obs(), r))

        with (
            patch("backend.services.analysis_service.engine.review_tracker._has_table", return_value=True),
            patch("backend.services.analysis_service.engine.review_tracker.SessionLocal") as mock_session_cls,
        ):
            mock_db = MagicMock()
            mock_session_cls.return_value = mock_db
            mock_query = MagicMock()
            mock_db.query.return_value = mock_query
            mock_query.join.return_value = mock_query
            mock_query.filter.return_value = mock_query
            mock_query.all.return_value = rows
            result = build_pool_simulation(lookback_days=90, strategy="auto")

        self.assertEqual(result["status"], "ok")
        a_t5 = result["by_tier"]["A"]["T+5"]
        self.assertEqual(a_t5["discipline"]["trades"], 12)
        self.assertEqual(a_t5["stopped"], 5)
        # Buy&hold expectancy: (7*4 + 5*-25)/12 = -8.08; discipline: (7*4 + 5*-10)/12 = -1.83
        self.assertAlmostEqual(a_t5["buy_hold"]["expectancy_pct"], round((7 * 4 + 5 * -25) / 12, 4), places=3)
        self.assertAlmostEqual(a_t5["discipline"]["expectancy_pct"], round((7 * 4 + 5 * -10) / 12, 4), places=3)
        self.assertGreater(a_t5["expectancy_delta_pct"], 0)  # discipline strictly better
        self.assertEqual(a_t5["discipline"]["worst_return_pct"], -10.0)
        self.assertEqual(a_t5["buy_hold"]["worst_return_pct"], -25.0)
        # ALL bucket mirrors the single tier here
        self.assertEqual(result["overall"]["T+5"]["discipline"]["trades"], 12)


if __name__ == "__main__":
    unittest.main()
