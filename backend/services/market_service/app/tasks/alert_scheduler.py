from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from backend.services.market_service.app.api.v1.alerts import check_all_active_alerts

logger = logging.getLogger(__name__)


class AlertScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._last_result: dict | None = None
        self._last_error: str | None = None
        self._last_run_at: str | None = None

    def enabled(self) -> bool:
        return os.getenv("ALERT_SCHEDULER_ENABLED", "true").lower() not in ("0", "false", "no")

    def interval_seconds(self) -> int:
        try:
            return max(30, int(os.getenv("ALERT_SCHEDULER_INTERVAL_SECONDS", "300")))
        except ValueError:
            return 300

    def max_alerts_per_run(self) -> int:
        try:
            return max(10, int(os.getenv("ALERT_SCHEDULER_MAX_ALERTS", "200")))
        except ValueError:
            return 200

    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    def status(self) -> dict:
        return {
            "enabled": self.enabled(),
            "running": self.running(),
            "interval_seconds": self.interval_seconds(),
            "max_alerts_per_run": self.max_alerts_per_run(),
            "last_run_at": self._last_run_at,
            "last_error": self._last_error,
            "last_result": self._last_result,
        }

    def start(self) -> None:
        if not self.enabled():
            logger.info("alert scheduler disabled")
            return
        if self.running():
            return
        self._task = asyncio.create_task(self._run(), name="alert-scheduler")
        logger.info("alert scheduler started")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        logger.info("alert scheduler stopped")

    async def run_once(self) -> dict:
        self._last_run_at = datetime.now().isoformat()
        try:
            result = await check_all_active_alerts(max_alerts=self.max_alerts_per_run())
            self._last_result = {
                "checked_count": result.get("checked_count", 0),
                "triggered_count": result.get("triggered_count", 0),
                "checked_at": result.get("checked_at"),
            }
            self._last_error = None
            return result
        except Exception as exc:
            self._last_error = str(exc)[:200]
            logger.warning("alert scheduler run failed: %s", exc)
            return {
                "checked_count": 0,
                "triggered_count": 0,
                "items": [],
                "checked_at": self._last_run_at,
                "error": self._last_error,
            }

    async def _run(self) -> None:
        await asyncio.sleep(5)
        while True:
            await self.run_once()
            await asyncio.sleep(self.interval_seconds())


alert_scheduler = AlertScheduler()
