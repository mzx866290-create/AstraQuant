from __future__ import annotations

import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from backend.services.analysis_service.engine import daily_pool_scheduler as scheduler


class DailyPoolSchedulerTests(unittest.TestCase):
    def test_news_enrich_target_rolls_to_next_day_after_deep_night_window(self) -> None:
        now = datetime(2026, 5, 18, 15, 45)

        target = scheduler._next_news_enrich_target(now)

        self.assertEqual(target, datetime(2026, 5, 19, 1, 30))

    def test_news_enrich_target_uses_same_day_before_deep_night_window(self) -> None:
        now = datetime(2026, 5, 19, 0, 45)

        target = scheduler._next_news_enrich_target(now)

        self.assertEqual(target, datetime(2026, 5, 19, 1, 30))

    def test_daily_pool_target_rolls_to_next_day_after_close_window(self) -> None:
        now = datetime(2026, 5, 18, 15, 45)

        target = scheduler._next_daily_pool_target(now, 15, 45)

        self.assertEqual(target, datetime(2026, 5, 19, 15, 45))

    def test_weekend_still_runs_news_enrich_after_nightly_window(self) -> None:
        pool_scheduler = scheduler.DailyPoolScheduler()
        now = datetime(2026, 5, 16, 8, 0)

        with patch.object(pool_scheduler, "_execute_news_enrich", new=AsyncMock()) as execute_news:
            asyncio.run(pool_scheduler._run_due_news_enrich(now))

        execute_news.assert_awaited_once()

    def test_weekend_does_not_run_base_pool_after_close_window(self) -> None:
        pool_scheduler = scheduler.DailyPoolScheduler()
        now = datetime(2026, 5, 16, 16, 0)

        with (
            patch.object(pool_scheduler, "_is_weekend", return_value=True),
            patch.object(pool_scheduler, "_execute", new=AsyncMock()) as execute_base,
        ):
            asyncio.run(pool_scheduler._run_due_base_pool(now))

        execute_base.assert_not_awaited()

    def test_catch_up_news_enrich_runs_after_nightly_window(self) -> None:
        pool_scheduler = scheduler.DailyPoolScheduler()
        now = datetime(2026, 5, 18, 8, 0)

        with patch.object(pool_scheduler, "_execute_news_enrich", new=AsyncMock()) as execute_news:
            asyncio.run(pool_scheduler._catch_up_news_enrich(now))

        execute_news.assert_awaited_once()

    def test_intraday_confirmation_timeout_does_not_block_scheduler(self) -> None:
        pool_scheduler = scheduler.DailyPoolScheduler()
        now = datetime(2026, 5, 18, 9, 36)

        async def slow_confirmation(*_args, **_kwargs):
            await asyncio.sleep(1)

        with (
            patch.object(pool_scheduler, "_is_weekend", return_value=False),
            patch.object(pool_scheduler, "_execute_intraday_confirmation", side_effect=slow_confirmation),
            patch.object(scheduler, "INTRADAY_CONFIRMATION_TIMEOUT_SECONDS", 0.01),
        ):
            asyncio.run(pool_scheduler._run_due_intraday_confirmation(now))

        self.assertIn("timed out", pool_scheduler._last_intraday_confirmation_error or "")
        self.assertEqual((pool_scheduler._last_intraday_confirmation_result or {}).get("status"), "timeout")

    def test_base_pool_timeout_is_recorded(self) -> None:
        pool_scheduler = scheduler.DailyPoolScheduler()
        now = datetime(2026, 5, 18, 16, 0)

        async def slow_base_pool():
            await asyncio.sleep(1)

        with (
            patch.object(pool_scheduler, "_is_weekend", return_value=False),
            patch.object(scheduler, "has_run_today", return_value=False),
            patch.object(pool_scheduler, "_execute", side_effect=slow_base_pool),
            patch.object(scheduler, "BASE_POOL_TIMEOUT_SECONDS", 0.01),
        ):
            asyncio.run(pool_scheduler._run_due_base_pool(now))

        self.assertIn("timed out", pool_scheduler._last_error or "")


if __name__ == "__main__":
    unittest.main()
