from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from backend.services.analysis_service.engine import model_health_scheduler as scheduler_module
from backend.services.analysis_service.engine.model_health_scheduler import ModelHealthScheduler


class _FakeQuery:
    def __init__(self, models: list[SimpleNamespace]) -> None:
        self.models = models
        self.filtered = False
        self.ordered = False

    def filter(self, *_args, **_kwargs):
        self.filtered = True
        return self

    def order_by(self, *_args, **_kwargs):
        self.ordered = True
        self.models = sorted(self.models, key=lambda model: (model.sort_order, model.id))
        return self

    def all(self):
        return list(self.models)


class _FakeDb:
    def __init__(self, models: list[SimpleNamespace] | None = None, *, fail_on_query: bool = False) -> None:
        self.query_obj = _FakeQuery(models or [])
        self.fail_on_query = fail_on_query
        self.closed = False

    def query(self, *_args, **_kwargs):
        if self.fail_on_query:
            raise RuntimeError("query failed")
        return self.query_obj

    def close(self) -> None:
        self.closed = True


def _model(model_id: int, sort_order: int) -> SimpleNamespace:
    return SimpleNamespace(id=model_id, sort_order=sort_order)


class _FakeTask:
    def __init__(self) -> None:
        self.cancel_called = False
        self.awaited = False

    def cancel(self) -> None:
        self.cancel_called = True

    def __await__(self):
        async def raise_cancelled():
            self.awaited = True
            raise asyncio.CancelledError

        return raise_cancelled().__await__()


class ModelHealthSchedulerQualityTests(unittest.IsolatedAsyncioTestCase):
    def test_enabled_and_interval_respect_environment_and_minimum(self) -> None:
        scheduler = ModelHealthScheduler()

        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(scheduler.enabled())
            self.assertEqual(scheduler.interval_seconds(), 1800)

        with patch.dict("os.environ", {"AI_MODEL_HEALTH_AUTORUN": "TRUE", "AI_MODEL_HEALTH_INTERVAL_SECONDS": "120"}, clear=True):
            self.assertTrue(scheduler.enabled())
            self.assertEqual(scheduler.interval_seconds(), 300)

        with patch.dict("os.environ", {"AI_MODEL_HEALTH_AUTORUN": "false", "AI_MODEL_HEALTH_INTERVAL_SECONDS": "900"}, clear=True):
            self.assertFalse(scheduler.enabled())
            self.assertEqual(scheduler.interval_seconds(), 900)

    async def test_start_respects_enabled_is_idempotent_and_stop_clears_task(self) -> None:
        scheduler = ModelHealthScheduler()

        with patch.dict("os.environ", {"AI_MODEL_HEALTH_AUTORUN": "false"}, clear=True):
            scheduler.start()

        self.assertIsNone(scheduler._task)

        first_probe_started = asyncio.Event()

        async def check_once() -> None:
            first_probe_started.set()

        scheduler.check_once = AsyncMock(side_effect=check_once)
        scheduler.interval_seconds = Mock(return_value=3600)

        with patch.dict("os.environ", {"AI_MODEL_HEALTH_AUTORUN": "true"}, clear=True):
            scheduler.start()
            first_task = scheduler._task
            scheduler.start()

        self.assertIsNotNone(first_task)
        self.assertIs(scheduler._task, first_task)
        self.assertEqual(first_task.get_name(), "ai-model-health-scheduler")

        await asyncio.wait_for(first_probe_started.wait(), timeout=1)
        scheduler.check_once.assert_awaited_once()

        await scheduler.stop()

        self.assertIsNone(scheduler._task)
        self.assertTrue(first_task.done())

    async def test_stop_without_task_is_noop_and_cancelled_task_is_cleared(self) -> None:
        scheduler = ModelHealthScheduler()

        await scheduler.stop()

        self.assertIsNone(scheduler._task)
        self.assertFalse(scheduler._stop.is_set())

        task = _FakeTask()
        scheduler._task = task

        await scheduler.stop()

        self.assertTrue(task.cancel_called)
        self.assertTrue(task.awaited)
        self.assertTrue(scheduler._stop.is_set())
        self.assertIsNone(scheduler._task)

    async def test_run_swallows_check_once_error_logs_and_continues(self) -> None:
        scheduler = ModelHealthScheduler()
        scheduler.interval_seconds = Mock(return_value=300)
        calls = 0

        async def check_once() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("probe exploded")
            scheduler._stop.set()

        scheduler.check_once = AsyncMock(side_effect=check_once)

        async def fake_wait_for(awaitable, timeout):
            awaitable.close()
            self.assertEqual(timeout, 300)
            if calls == 1:
                raise asyncio.TimeoutError
            return True

        with self.assertLogs(scheduler_module.logger.name, level="WARNING") as logs:
            with patch("backend.services.analysis_service.engine.model_health_scheduler.asyncio.wait_for", side_effect=fake_wait_for):
                await scheduler._run()

        self.assertEqual(scheduler.check_once.await_count, 2)
        self.assertIn("AI model health scheduled check failed: probe exploded", "\n".join(logs.output))

    async def test_check_once_closes_db_and_probes_active_models_in_sort_order(self) -> None:
        models = [_model(3, 20), _model(1, 10), _model(2, 10)]
        db = _FakeDb(models)
        probe = AsyncMock()

        with patch("backend.services.analysis_service.engine.model_health_scheduler.SessionLocal", return_value=db):
            with patch("backend.services.analysis_service.engine.model_health_scheduler.model_health_checker.probe", probe):
                await ModelHealthScheduler().check_once()

        self.assertTrue(db.query_obj.filtered)
        self.assertTrue(db.query_obj.ordered)
        self.assertTrue(db.closed)
        self.assertEqual([call.args[0].id for call in probe.await_args_list], [1, 2, 3])
        self.assertTrue(all(call.args[1] is scheduler_module.ai_client for call in probe.await_args_list))
        self.assertEqual([call.kwargs["analysis_grade"] for call in probe.await_args_list], [False, False, False])

    async def test_check_once_closes_db_when_query_raises(self) -> None:
        db = _FakeDb(fail_on_query=True)

        with patch("backend.services.analysis_service.engine.model_health_scheduler.SessionLocal", return_value=db):
            with self.assertRaises(RuntimeError) as ctx:
                await ModelHealthScheduler().check_once()

        self.assertEqual(str(ctx.exception), "query failed")
        self.assertTrue(db.closed)


if __name__ == "__main__":
    unittest.main()
