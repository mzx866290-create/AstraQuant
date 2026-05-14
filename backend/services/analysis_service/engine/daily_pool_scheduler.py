"""每日观察池定时调度器 — 15:35 自动触发 pipeline，启动时补采"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

from backend.services.analysis_service.engine.daily_pool_pipeline import (
    has_run_today,
    run_daily_pool_pipeline,
)

logger = logging.getLogger(__name__)


class DailyPoolScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_result: dict | None = None
        self._last_error: str | None = None
        self._last_run_at: str | None = None

    def enabled(self) -> bool:
        return os.getenv("DAILY_POOL_SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

    def target_hour(self) -> int:
        try:
            return int(os.getenv("DAILY_POOL_HOUR", "15"))
        except ValueError:
            return 15

    def target_minute(self) -> int:
        try:
            return int(os.getenv("DAILY_POOL_MINUTE", "35"))
        except ValueError:
            return 35

    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    def status(self) -> dict:
        return {
            "enabled": self.enabled(),
            "running": self.running(),
            "target_time": f"{self.target_hour():02d}:{self.target_minute():02d}",
            "last_run_at": self._last_run_at,
            "last_error": self._last_error,
            "last_result_summary": _summarize(self._last_result),
        }

    def start(self) -> None:
        if not self.enabled() or self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="daily-pool-scheduler")
        logger.info("daily pool scheduler started (target %02d:%02d)", self.target_hour(), self.target_minute())

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
        logger.info("daily pool scheduler stopped")

    async def run_now(self) -> dict:
        """手动触发一次 pipeline（管理员用）"""
        return await self._execute()

    async def _run(self) -> None:
        await self._catch_up()
        while not self._stop.is_set():
            try:
                await self._wait_until_target()
                if self._stop.is_set():
                    break
                if self._is_weekend():
                    logger.info("Skipping daily pool: weekend")
                    await self._sleep_until_tomorrow()
                    continue
                await self._execute()
                await self._sleep_until_tomorrow()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Daily pool scheduler error: {e}")
                self._last_error = str(e)
                await asyncio.sleep(300)

    async def _catch_up(self) -> None:
        """启动时检查：如果今天是交易日且还没跑过，且已过目标时间，自动补一次"""
        if self._is_weekend():
            return
        now = datetime.now()
        target_h = self.target_hour()
        target_m = self.target_minute()
        if now.hour < target_h or (now.hour == target_h and now.minute < target_m):
            return
        if has_run_today():
            logger.info("Catch-up check: pipeline already ran today, skipping")
            return
        logger.info("Catch-up: pipeline missed today, running now")
        await self._execute()

    async def _execute(self) -> dict:
        trade_date = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"Executing daily pool pipeline for {trade_date}")
        self._last_run_at = datetime.now().isoformat()
        self._last_error = None
        try:
            result = await run_daily_pool_pipeline(trade_date)
            self._last_result = result
            return result
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"Pipeline execution failed: {e}")
            return {"status": "error", "error": str(e), "trade_date": trade_date}

    async def _wait_until_target(self) -> None:
        """等待到目标时间"""
        now = datetime.now()
        target_h = self.target_hour()
        target_m = self.target_minute()

        target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
        if now >= target:
            return

        wait_seconds = (target - now).total_seconds()
        if wait_seconds > 0:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass

    async def _sleep_until_tomorrow(self) -> None:
        """睡到明天的目标时间前 1 小时"""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=3600 * 20)
        except asyncio.TimeoutError:
            pass

    def _is_weekend(self) -> bool:
        return datetime.now().weekday() >= 5


def _summarize(result: dict | None) -> dict | None:
    if not result:
        return None
    return {
        "status": result.get("status"),
        "trade_date": result.get("trade_date"),
        "recommendations_count": result.get("recommendations_count"),
    }


daily_pool_scheduler = DailyPoolScheduler()
