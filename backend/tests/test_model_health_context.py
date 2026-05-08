from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from backend.services.analysis_service.engine.context_builder import ContextBuilder
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
    def __init__(self, models: list[SimpleNamespace]) -> None:
        self.query_obj = _FakeQuery(models)
        self.closed = False

    def query(self, *_args, **_kwargs):
        return self.query_obj

    def close(self) -> None:
        self.closed = True


def _model(model_id: int, sort_order: int) -> SimpleNamespace:
    return SimpleNamespace(id=model_id, sort_order=sort_order)


def _stock_data() -> dict:
    return {
        "symbol": "600519",
        "name": "Unit Stock",
        "price": 100.5,
        "quote_source": "eastmoney",
        "kline_source": "eastmoney",
        "quote": {
            "open": 99.0,
            "high": 101.0,
            "low": 98.5,
            "volume": 123456,
            "turnover": 7890,
            "pe_ttm": 20.1,
            "pb": 4.2,
            "timestamp": "2026-05-07T10:00:00+00:00",
            "source": "eastmoney",
        },
        "kline_data": [{"date": f"2026-04-{day:02d}", "close": 90 + day} for day in range(1, 21)],
        "financial": {
            "report_date": "2026-03-31",
            "revenue": 1000,
            "net_profit": 200,
            "operating_cf": 180,
            "pe_ttm": 19.8,
            "pb": 4.1,
            "source": "akshare",
        },
        "announcements": [{"announce_date": "2026-05-01", "title": "unit"}],
        "news": [{"publish_time": "2026-05-06T09:00:00+00:00", "title": "unit news"}],
        "news_sentiment": {"total": 1, "validation_note": "sentiment ok"},
        "industry_event_context": {
            "available": True,
            "note": "industry context ok",
            "themes": [{"evidence": [{"publish_time": "2026-05-06T08:00:00+00:00"}]}],
        },
    }


class ModelHealthSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def test_enabled_and_interval_respect_environment_bounds(self) -> None:
        scheduler = ModelHealthScheduler()

        with patch.dict("os.environ", {"AI_MODEL_HEALTH_AUTORUN": "TRUE", "AI_MODEL_HEALTH_INTERVAL_SECONDS": "120"}, clear=False):
            self.assertTrue(scheduler.enabled())
            self.assertEqual(scheduler.interval_seconds(), 300)

        with patch.dict("os.environ", {"AI_MODEL_HEALTH_AUTORUN": "false", "AI_MODEL_HEALTH_INTERVAL_SECONDS": "900"}, clear=False):
            self.assertFalse(scheduler.enabled())
            self.assertEqual(scheduler.interval_seconds(), 900)

    async def test_start_creates_single_task_only_when_enabled_and_stop_cancels_it(self) -> None:
        scheduler = ModelHealthScheduler()
        created = []

        async def never_finishes():
            await asyncio.Event().wait()

        class _Task:
            def __init__(self, coro) -> None:
                self.coro = coro
                self.cancelled = False

            def cancel(self) -> None:
                self.cancelled = True
                self.coro.close()

            def __await__(self):
                async def _raise_cancelled():
                    raise asyncio.CancelledError

                return _raise_cancelled().__await__()

        def fake_create_task(coro, name=None):
            created.append((coro, name))
            return _Task(coro)

        with patch.dict("os.environ", {"AI_MODEL_HEALTH_AUTORUN": "true"}, clear=False):
            with patch("backend.services.analysis_service.engine.model_health_scheduler.asyncio.create_task", side_effect=fake_create_task):
                scheduler._run = never_finishes
                scheduler.start()
                scheduler.start()

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0][1], "ai-model-health-scheduler")
        await scheduler.stop()
        self.assertIsNone(scheduler._task)

    async def test_run_exits_when_stop_is_set_by_check_once_without_sleeping(self) -> None:
        scheduler = ModelHealthScheduler()
        scheduler.interval_seconds = Mock(return_value=999)

        async def check_and_stop():
            scheduler._stop.set()

        scheduler.check_once = AsyncMock(side_effect=check_and_stop)

        await scheduler._run()

        scheduler.check_once.assert_awaited_once()
        scheduler.interval_seconds.assert_called_once()

    async def test_run_timeout_boundary_rechecks_stop_before_next_probe(self) -> None:
        scheduler = ModelHealthScheduler()
        scheduler.check_once = AsyncMock()
        scheduler.interval_seconds = Mock(return_value=300)

        async def timeout_and_stop(awaitable, timeout):
            awaitable.close()
            self.assertEqual(timeout, 300)
            scheduler._stop.set()
            raise asyncio.TimeoutError

        with patch("backend.services.analysis_service.engine.model_health_scheduler.asyncio.wait_for", side_effect=timeout_and_stop):
            await scheduler._run()

        scheduler.check_once.assert_awaited_once()

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
        self.assertTrue(all(call.args[1] is not None for call in probe.await_args_list))
        self.assertEqual([call.kwargs["analysis_grade"] for call in probe.await_args_list], [False, False, False])


class ContextBuilderTests(unittest.TestCase):
    def test_enrich_adds_quality_and_ready_context_without_mutating_input(self) -> None:
        source = _stock_data()
        enriched = ContextBuilder().enrich(source, models_count=2, quota_ready=True)

        self.assertIsNot(enriched, source)
        self.assertNotIn("data_quality", source)
        self.assertNotIn("readiness", source)
        self.assertEqual(enriched["symbol"], "600519")
        self.assertEqual(enriched["readiness"]["ready"], True)
        self.assertEqual(enriched["readiness"]["blocking"], [])
        self.assertEqual(enriched["readiness"]["data_grade"]["grade"], "A")
        self.assertEqual(enriched["readiness"]["items"]["ai_model"]["count"], 2)
        self.assertEqual(enriched["readiness"]["items"]["kline"]["count"], 20)
        self.assertEqual(enriched["data_quality"]["quote"]["source"], "eastmoney")
        self.assertEqual(enriched["data_quality"]["financial"]["updated_at"], "2026-03-31")

    def test_enrich_reports_blocking_quota_and_missing_context_for_sparse_data(self) -> None:
        sparse = {"symbol": "000001", "price": 0, "quote": {}, "kline_data": []}

        enriched = ContextBuilder().enrich(sparse, models_count=0, quota_ready=False, quota_message="quota exhausted")
        readiness = enriched["readiness"]

        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["blocking"], ["ai_model", "quota"])
        self.assertIn("quote", readiness["missing_context"])
        self.assertIn("kline", readiness["missing_context"])
        self.assertEqual(readiness["items"]["quota"]["message"], "quota exhausted")
        self.assertIn("latest_price_missing_or_zero", enriched["data_quality"]["quote"]["warnings"])
        self.assertIn("kline_missing", enriched["data_quality"]["kline"]["warnings"])


if __name__ == "__main__":
    unittest.main()
