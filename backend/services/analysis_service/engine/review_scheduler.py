from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime

from backend.services.analysis_service.engine.review_tracker import build_review_report, run_pending_reviews

logger = logging.getLogger(__name__)


class ReviewScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_result: dict | None = None
        self._last_error: str | None = None
        self._last_run_at: str | None = None

    def enabled(self) -> bool:
        return os.getenv("REVIEW_SCHEDULER_ENABLED", "false").lower() in {"1", "true", "yes", "on"}

    def interval_seconds(self) -> int:
        try:
            return max(300, int(os.getenv("REVIEW_SCHEDULER_INTERVAL_SECONDS", "3600")))
        except ValueError:
            return 3600

    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    def status(self) -> dict:
        return {
            "enabled": self.enabled(),
            "running": self.running(),
            "interval_seconds": self.interval_seconds(),
            "last_run_at": self._last_run_at,
            "last_error": self._last_error,
            "last_result": self._last_result,
        }

    def start(self) -> None:
        if not self.enabled() or self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="review-scheduler")
        logger.info("review scheduler started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("review scheduler stopped")

    async def run_once(self, review_date: date | None = None) -> dict:
        review_date = review_date or date.today()
        self._last_run_at = datetime.now().isoformat()
        try:
            run_result = await run_pending_reviews(review_date)
            report = build_review_report()
            self._last_result = {
                "review_date": review_date.isoformat(),
                "processed": run_result.get("processed", 0),
                "created": run_result.get("created", 0),
                "status": run_result.get("status"),
                "report_summary": report.get("summary", {}),
            }
            self._last_error = None
            return {
                "run_pending_reviews": run_result,
                "review_report": report,
            }
        except Exception as exc:
            self._last_error = str(exc)[:200]
            logger.warning("review scheduler run failed: %s", exc)
            return {
                "run_pending_reviews": {
                    "review_date": review_date.isoformat(),
                    "processed": 0,
                    "created": 0,
                    "status": "error",
                    "error": self._last_error,
                },
                "review_report": {
                    "status": "error",
                    "summary": {},
                    "by_strategy": [],
                },
            }

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds())
            except asyncio.TimeoutError:
                continue


review_scheduler = ReviewScheduler()
