"""每日观察池定时调度器 — 15:45 自动触发 pipeline；01:30 资讯影响增强"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta

from backend.services.analysis_service.engine.daily_pool_pipeline import (
    has_run_today,
    run_daily_pool_pipeline,
)
from backend.services.analysis_service.engine.intraday_confirmation import (
    build_intraday_confirmation,
    confirmation_window_label,
    next_confirmation_target,
)

logger = logging.getLogger(__name__)

NEWS_ENRICH_HOUR = int(os.getenv("NEWS_ENRICH_HOUR", "1"))
NEWS_ENRICH_MINUTE = int(os.getenv("NEWS_ENRICH_MINUTE", "30"))
BASE_POOL_TIMEOUT_SECONDS = int(os.getenv("DAILY_POOL_TIMEOUT_SECONDS", "1800"))
NEWS_ENRICH_TIMEOUT_SECONDS = int(os.getenv("NEWS_ENRICH_TIMEOUT_SECONDS", "1800"))
INTRADAY_CONFIRMATION_TIMEOUT_SECONDS = int(os.getenv("INTRADAY_CONFIRMATION_TIMEOUT_SECONDS", "180"))


def _next_daily_pool_target(now: datetime, hour: int, minute: int) -> datetime:
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target


def _next_news_enrich_target(now: datetime) -> datetime:
    target = now.replace(hour=NEWS_ENRICH_HOUR, minute=NEWS_ENRICH_MINUTE, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target


class DailyPoolScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_result: dict | None = None
        self._last_error: str | None = None
        self._last_run_at: str | None = None
        self._last_news_enrich_at: str | None = None
        self._last_news_enrich_result: dict | None = None
        self._last_news_enrich_error: str | None = None
        self._last_intraday_confirmation_at: str | None = None
        self._last_intraday_confirmation_result: dict | None = None
        self._last_intraday_confirmation_error: str | None = None

    def enabled(self) -> bool:
        return os.getenv("DAILY_POOL_SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

    def target_hour(self) -> int:
        try:
            return int(os.getenv("DAILY_POOL_HOUR", "15"))
        except ValueError:
            return 15

    def target_minute(self) -> int:
        try:
            return int(os.getenv("DAILY_POOL_MINUTE", "45"))
        except ValueError:
            return 45

    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    def status(self) -> dict:
        return {
            "enabled": self.enabled(),
            "running": self.running(),
            "target_time": f"{self.target_hour():02d}:{self.target_minute():02d}",
            "news_enrich_time": f"{NEWS_ENRICH_HOUR:02d}:{NEWS_ENRICH_MINUTE:02d}",
            "last_run_at": self._last_run_at,
            "last_error": self._last_error,
            "last_result_summary": _summarize(self._last_result),
            "last_news_enrich_at": self._last_news_enrich_at,
            "last_news_enrich_error": self._last_news_enrich_error,
            "last_news_enrich_result": self._last_news_enrich_result,
            "intraday_confirmation_windows": ["09:35", "09:45", "10:00"],
            "last_intraday_confirmation_at": self._last_intraday_confirmation_at,
            "last_intraday_confirmation_error": self._last_intraday_confirmation_error,
            "last_intraday_confirmation_result": self._last_intraday_confirmation_result,
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
                await self._wait_until_next_job()
                if self._stop.is_set():
                    break
                now = datetime.now()
                await self._run_due_base_pool(now)
                await self._run_due_news_enrich(now)
                await self._run_due_intraday_confirmation(now)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Daily pool scheduler error: {e}")
                self._last_error = str(e)
                await asyncio.sleep(300)

    async def _wait_until_next_job(self) -> None:
        now = datetime.now()
        target = min(
            _next_daily_pool_target(now, self.target_hour(), self.target_minute()),
            _next_news_enrich_target(now),
            next_confirmation_target(now),
        )
        wait_seconds = (target - now).total_seconds()
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=wait_seconds)
        except asyncio.TimeoutError:
            pass

    async def _run_due_base_pool(self, now: datetime) -> None:
        target = now.replace(hour=self.target_hour(), minute=self.target_minute(), second=0, microsecond=0)
        if now < target:
            return
        if self._is_weekend():
            logger.info("Skipping daily pool: weekend")
            return
        if has_run_today():
            logger.info("Daily pool already ran today, skipping")
            return
        try:
            await asyncio.wait_for(self._execute(), timeout=BASE_POOL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._last_error = f"daily pool timed out after {BASE_POOL_TIMEOUT_SECONDS}s"
            logger.error(self._last_error)

    async def _run_due_news_enrich(self, now: datetime) -> None:
        target = now.replace(hour=NEWS_ENRICH_HOUR, minute=NEWS_ENRICH_MINUTE, second=0, microsecond=0)
        if now < target:
            return
        if self._last_news_enrich_at and self._last_news_enrich_at[:10] == now.date().isoformat():
            return
        try:
            await asyncio.wait_for(self._execute_news_enrich(), timeout=NEWS_ENRICH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._last_news_enrich_error = f"news enrichment timed out after {NEWS_ENRICH_TIMEOUT_SECONDS}s"
            self._last_news_enrich_result = {"status": "timeout", "error": self._last_news_enrich_error}
            logger.error(self._last_news_enrich_error)

    async def _run_due_intraday_confirmation(self, now: datetime) -> None:
        if self._is_weekend():
            return
        label = confirmation_window_label(now)
        if label == "preopen":
            return
        marker = f"{now.date().isoformat()}T{label}"
        if self._last_intraday_confirmation_at == marker:
            return
        try:
            await asyncio.wait_for(
                self._execute_intraday_confirmation(marker),
                timeout=INTRADAY_CONFIRMATION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            self._last_intraday_confirmation_error = (
                f"intraday confirmation timed out after {INTRADAY_CONFIRMATION_TIMEOUT_SECONDS}s"
            )
            self._last_intraday_confirmation_result = {
                "status": "timeout",
                "error": self._last_intraday_confirmation_error,
                "window": confirmation_window_label(now),
            }
            logger.error(self._last_intraday_confirmation_error)

    async def _execute_news_enrich(self, trade_date: str | None = None) -> dict:
        logger.info("Running nightly news enrichment for %s", trade_date or "latest observation pool")
        self._last_news_enrich_at = datetime.now().isoformat()
        self._last_news_enrich_error = None
        try:
            from backend.services.analysis_service.engine.news_enricher import enrich_with_news
            result = await enrich_with_news(trade_date)
            self._last_news_enrich_result = result
            logger.info("News enrichment result: %s", result)
            return result
        except Exception as e:
            self._last_news_enrich_error = str(e)
            logger.error("News enrichment failed: %s", e)
            return {"status": "error", "error": str(e), "trade_date": trade_date}

    async def _catch_up(self) -> None:
        """启动时检查：如果今天是交易日且还没跑过，且已过目标时间，自动补一次"""
        now = datetime.now()
        target_h = self.target_hour()
        target_m = self.target_minute()
        if (
            not self._is_weekend()
            and (now.hour > target_h or (now.hour == target_h and now.minute >= target_m))
        ):
            if has_run_today():
                logger.info("Catch-up check: pipeline already ran today, skipping")
            else:
                logger.info("Catch-up: pipeline missed today, running now")
                try:
                    await asyncio.wait_for(self._execute(), timeout=BASE_POOL_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    self._last_error = f"daily pool timed out after {BASE_POOL_TIMEOUT_SECONDS}s"
                    logger.error(self._last_error)

        await self._catch_up_news_enrich(now)
        await self._run_due_intraday_confirmation(now)

    async def _catch_up_news_enrich(self, now: datetime) -> None:
        """启动时如果已经过夜间窗口，则围绕最新观察池补一次资讯增强。"""
        target = now.replace(hour=NEWS_ENRICH_HOUR, minute=NEWS_ENRICH_MINUTE, second=0, microsecond=0)
        if now < target:
            return
        if self._last_news_enrich_at and self._last_news_enrich_at[:10] == now.date().isoformat():
            return
        try:
            await asyncio.wait_for(self._execute_news_enrich(), timeout=NEWS_ENRICH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._last_news_enrich_error = f"news enrichment timed out after {NEWS_ENRICH_TIMEOUT_SECONDS}s"
            self._last_news_enrich_result = {"status": "timeout", "error": self._last_news_enrich_error}
            logger.error(self._last_news_enrich_error)

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

    async def _execute_intraday_confirmation(self, marker: str | None = None) -> dict:
        self._last_intraday_confirmation_error = None
        marker = marker or f"{datetime.now().date().isoformat()}T{confirmation_window_label()}"
        self._last_intraday_confirmation_at = marker
        try:
            from backend.services.analysis_service.api.v1.scoring import get_recommendations

            pool = await get_recommendations(
                request=None,
                market="ALL",
                limit=20,
                max_candidates=200,
                force_refresh=False,
                strategy="auto",
                include_evidence=True,
                include_debate=False,
                concurrency=8,
                initial_full_scan=False,
            )
            result = await build_intraday_confirmation(pool.get("recommendations") or [], concurrency=8)
            self._last_intraday_confirmation_result = {
                "status": result.get("status"),
                "window": result.get("window"),
                "checked_at": result.get("checked_at"),
                "summary": result.get("summary"),
            }
            logger.info("Intraday confirmation result: %s", self._last_intraday_confirmation_result)
            return result
        except Exception as e:
            self._last_intraday_confirmation_error = str(e)
            logger.error("Intraday confirmation failed: %s", e)
            return {"status": "error", "error": str(e)}

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
