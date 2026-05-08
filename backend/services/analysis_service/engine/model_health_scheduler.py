from __future__ import annotations

import asyncio
import logging
import os

from backend.shared.database import SessionLocal
from backend.shared.models import AIModel
from backend.services.analysis_service.engine.ai_client import ai_client
from backend.services.analysis_service.engine.model_router import model_health_checker

logger = logging.getLogger(__name__)


class ModelHealthScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def enabled(self) -> bool:
        return os.getenv("AI_MODEL_HEALTH_AUTORUN", "false").lower() == "true"

    def interval_seconds(self) -> int:
        return max(300, int(os.getenv("AI_MODEL_HEALTH_INTERVAL_SECONDS", "1800")))

    def start(self) -> None:
        if not self.enabled() or self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="ai-model-health-scheduler")
        logger.info("AI model health scheduler started")

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
        logger.info("AI model health scheduler stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.check_once()
            except Exception as exc:
                logger.warning("AI model health scheduled check failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds())
            except asyncio.TimeoutError:
                continue

    async def check_once(self) -> None:
        db = SessionLocal()
        try:
            models = (
                db.query(AIModel)
                .filter(AIModel.is_active == True)
                .order_by(AIModel.sort_order, AIModel.id)
                .all()
            )
        finally:
            db.close()
        for model in models:
            await model_health_checker.probe(model, ai_client, analysis_grade=False)


model_health_scheduler = ModelHealthScheduler()
