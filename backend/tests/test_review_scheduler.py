from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.analysis_service.engine.review_scheduler import ReviewScheduler


class ReviewSchedulerTests(unittest.TestCase):
    def test_status_reports_disabled_by_default(self) -> None:
        scheduler = ReviewScheduler()
        status = scheduler.status()

        self.assertFalse(status["enabled"])
        self.assertFalse(status["running"])

    def test_run_once_aggregates_runner_and_report(self) -> None:
        scheduler = ReviewScheduler()
        with patch(
            "backend.services.analysis_service.engine.review_scheduler.run_pending_reviews",
            AsyncMock(return_value={"processed": 2, "created": 2, "status": "ok"}),
        ), patch(
            "backend.services.analysis_service.engine.review_scheduler.build_review_report",
            return_value={"status": "ok", "summary": {"reviews": 2}, "by_strategy": []},
        ):
            result = asyncio.run(scheduler.run_once())

        self.assertEqual(result["run_pending_reviews"]["processed"], 2)
        self.assertEqual(result["review_report"]["summary"]["reviews"], 2)
        self.assertEqual(scheduler.status()["last_result"]["created"], 2)


if __name__ == "__main__":
    unittest.main()
