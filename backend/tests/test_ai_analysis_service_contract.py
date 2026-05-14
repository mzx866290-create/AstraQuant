from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.analysis_service.engine import ai_analysis_service as service
from backend.shared.models import AIModel, AIUsageLog
from backend.shared.schemas import AIAnalysisRequest, AIAnalysisResponse


def _model(
    model_id: int,
    *,
    name: str | None = None,
    allowed_roles: str | None = "free,premium,admin",
    sort_order: int = 0,
    is_active: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=model_id,
        name=name or f"model-{model_id}",
        provider="openai",
        model_id=f"external-{model_id}",
        api_key_encrypted=f"encrypted-{model_id}",
        api_base_url=None,
        description=f"description-{model_id}",
        config={},
        is_active=is_active,
        allowed_roles=allowed_roles,
        sort_order=sort_order,
    )


def _user(*, user_id: int = 42, role: str | None = "free") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=role)


def _analysis_request(**overrides) -> SimpleNamespace:
    data = {
        "model_id": 1,
        "symbol": "000001",
        "question": "What changed?",
        "framework": None,
        "include_news": True,
        "report_template": "quick",
        "report_mode": "summary",
        "audience": "normal",
        "prompt_style": "default",
        "force_refresh": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _stock_data() -> dict:
    kline = [{"date": f"2026-04-{day:02d}", "close": 9.0 + day / 10} for day in range(1, 22)]
    return {
        "name": "Unit Bank",
        "price": 11.1,
        "change_pct": 1.2,
        "quote": {
            "source": "quote-unit",
            "open": 10.9,
            "high": 11.3,
            "low": 10.8,
            "volume": 1000,
            "turnover": 2000,
            "pe_ttm": 12.3,
            "pb": 1.4,
        },
        "quote_source": "quote-unit",
        "kline_source": "kline-unit",
        "kline_data": kline,
        "financial": {
            "report_date": "2026-03-31",
            "source": "financial-unit",
            "valuation_source": "valuation-unit",
            "revenue": 100_000_000,
            "net_profit": 12_000_000,
            "operating_cf": 10_000_000,
            "pe_ttm": 12.3,
            "pb": 1.4,
        },
        "announcements": [{"title": "Unit disclosure", "announce_date": "2026-05-06"}],
        "news": [{"title": "Unit news", "publish_time": "2026-05-06T09:00:00+00:00"}],
        "news_sentiment": {
            "total": 1,
            "count_dominant_sentiment": "neutral",
            "weighted_dominant_sentiment": "neutral",
            "validation_note": "",
        },
        "industry_event_context": {
            "available": True,
            "themes": [
                {
                    "theme": "banking",
                    "direction": "neutral",
                    "confidence": "medium",
                    "note": "unit evidence",
                    "evidence": [{"title": "industry note", "publish_time": "2026-05-06T08:00:00+00:00"}],
                }
            ],
            "warnings": [],
            "note": "unit event context",
        },
    }


def _cached_response() -> dict:
    return {
        "symbol": "000001",
        "model_name": "cached-model",
        "analysis": "cached analysis",
        "tokens_used": 12,
        "response_time_ms": 12,
        "created_at": datetime(2026, 5, 7, tzinfo=timezone.utc),
        "requested_model": "cached-model",
        "actual_model": "cached-model",
        "fallback_reason": None,
        "data_quality": {"quote": {"source": "cache"}},
        "readiness": {"ready": True},
        "risk_lights": {},
        "trust_boundary": {},
        "report_meta": {"force_refresh": False, "status": "success"},
        "cache_hit": True,
    }


class _FakeQuery:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = list(rows)

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        self.rows = sorted(self.rows, key=lambda row: (getattr(row, "sort_order", 0), getattr(row, "id", 0)))
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def count(self):
        return len(self.rows)


class _FakeDb:
    def __init__(self, models: list[SimpleNamespace] | None = None) -> None:
        self.models = list(models or [])
        self.added: list[object] = []
        self.commit_count = 0

    def query(self, entity):
        if entity is AIModel:
            return _FakeQuery([model for model in self.models if getattr(model, "is_active", True)])
        return _FakeQuery([])

    def add(self, item) -> None:
        self.added.append(item)

    def commit(self) -> None:
        self.commit_count += 1


class AIAnalysisServiceContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_available_models_filters_roles_and_attaches_health(self) -> None:
        db = _FakeDb(
            [
                _model(2, name="premium-only", allowed_roles="premium", sort_order=1),
                _model(3, name="default-roles", allowed_roles=None, sort_order=2),
                _model(1, name="free-model", allowed_roles="free,admin", sort_order=3),
            ]
        )
        health = AsyncMock(
            side_effect=lambda model_id: {
                "status": f"healthy-{model_id}",
                "latency_ms": 100 + model_id,
                "checked_at": "2026-05-07T00:00:00+00:00",
            }
        )

        with patch.object(service.model_health_checker, "get_cached", health):
            available = await service.list_available_models(_user(role="free"), db)

        self.assertEqual([model.id for model in available], [3, 1])
        self.assertEqual(available[0].health_status, "healthy-3")
        self.assertEqual(available[1].health_latency_ms, 101)
        self.assertEqual([call.args[0] for call in health.await_args_list], [3, 1])

    async def test_get_quota_resets_stale_daily_and_monthly_windows(self) -> None:
        db = _FakeDb()
        quota = SimpleNamespace(
            user_id=7,
            daily_limit=10,
            monthly_limit=100,
            daily_used=8,
            monthly_used=80,
            last_reset_daily=datetime(2000, 1, 1),
            last_reset_monthly=datetime(2000, 1, 1),
        )

        with patch("backend.shared.auth.get_user_quota", return_value=quota):
            response = await service.get_quota(_user(user_id=7), db)

        self.assertEqual(response.daily_used, 0)
        self.assertEqual(response.monthly_used, 0)
        self.assertEqual(response.daily_remaining, 10)
        self.assertEqual(response.monthly_remaining, 100)
        self.assertEqual(db.commit_count, 2)

    async def test_get_quota_clamps_negative_remaining_without_reset(self) -> None:
        db = _FakeDb()
        quota = SimpleNamespace(
            user_id=8,
            daily_limit=10,
            monthly_limit=100,
            daily_used=12,
            monthly_used=125,
            last_reset_daily=datetime.now(timezone.utc),
            last_reset_monthly=datetime.now(timezone.utc),
        )

        with patch("backend.shared.auth.get_user_quota", return_value=quota):
            response = await service.get_quota(_user(user_id=8), db)

        self.assertEqual(response.daily_remaining, 0)
        self.assertEqual(response.monthly_remaining, 0)
        self.assertEqual(db.commit_count, 0)

    async def test_cache_helpers_apply_category_and_mark_cache_hits(self) -> None:
        cache = SimpleNamespace(
            get=AsyncMock(return_value={"analysis": "cached body", "report_meta": {"force_refresh": True}}),
            set=AsyncMock(),
        )

        async def fake_cache_manager():
            return cache

        with patch.object(service, "get_cache_manager", fake_cache_manager):
            cached = await service._cache_get("cache-key", category="contract-category")
            await service._cache_set("write-key", {"ok": True}, category="write-category")

        self.assertTrue(cached["cache_hit"])
        self.assertFalse(cached["report_meta"]["force_refresh"])
        cache.get.assert_awaited_once_with("contract-category", "cache-key")
        cache.set.assert_awaited_once_with("write-category", "write-key", value={"ok": True})

    async def test_ai_analysis_schema_exposes_frontend_contract_fields(self) -> None:
        request = AIAnalysisRequest(
            model_id=1,
            symbol="000001",
            question="What changed?",
            framework="valuation",
        )
        response = AIAnalysisResponse(
            symbol="000001",
            model_name="primary",
            analysis="contract analysis body",
            tokens_used=24,
            response_time_ms=321,
            created_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
        )

        self.assertEqual(request.framework, "valuation")
        self.assertEqual(response.tokens_used, 24)
        self.assertIn("framework", AIAnalysisRequest.model_fields)
        self.assertIn("tokens_used", AIAnalysisResponse.model_fields)

    async def test_analyze_stock_cache_hit_short_circuits_model_and_usage_recording(self) -> None:
        db = _FakeDb([_model(1, name="primary")])
        cache_get = AsyncMock(return_value=_cached_response())
        stock_data = AsyncMock()
        router = AsyncMock()
        record_usage = MagicMock()

        with patch.object(service, "check_quota_available", return_value=(True, "")):
            with patch.object(service, "_cache_get", cache_get):
                with patch.object(service, "get_stock_data", stock_data):
                    with patch.object(service.model_router, "analyze_with_fallback", router):
                        with patch.object(service, "_record_ai_usage", record_usage):
                            response = await service.analyze_stock(_analysis_request(), _user(), db)

        self.assertTrue(response.cache_hit)
        self.assertEqual(response.analysis, "cached analysis")
        cache_get.assert_awaited_once()
        stock_data.assert_not_awaited()
        router.assert_not_awaited()
        record_usage.assert_not_called()
        self.assertEqual(db.commit_count, 0)

    async def test_analyze_stock_success_records_usage_and_caches_normalized_response(self) -> None:
        requested_model = _model(1, name="primary")
        db = _FakeDb([requested_model])
        request = _analysis_request(force_refresh=True)
        result = {
            "content": (
                "Unit analysis focuses on observable facts, data gaps, and risk controls. "
                "It is for learning and reference, not personalized investment advice."
            ),
            "prompt_tokens": 11,
            "completion_tokens": 13,
            "total_tokens": 24,
            "cost": 0.12,
            "response_time_ms": 321,
        }
        router = AsyncMock(return_value=(result, requested_model, None))
        cache_set = AsyncMock()

        with patch.object(service, "check_quota_available", return_value=(True, "")):
            with patch.object(service, "get_stock_data", AsyncMock(return_value=_stock_data())):
                with patch.object(service.model_router, "analyze_with_fallback", router):
                    with patch.object(service, "_cache_set", cache_set):
                        with patch.object(service, "increment_quota") as increment_quota:
                            response = await service.analyze_stock(request, _user(), db)

        self.assertEqual(response.actual_model, "primary")
        self.assertEqual(response.report_meta["status"], "success")
        self.assertTrue(response.report_meta["force_refresh"])
        self.assertFalse(response.cache_hit)
        self.assertEqual(len(db.added), 1)
        self.assertIsInstance(db.added[0], AIUsageLog)
        self.assertEqual(db.added[0].status, "success")
        self.assertEqual(db.added[0].total_tokens, 24)
        self.assertEqual(db.added[0].model_id, requested_model.id)
        self.assertEqual(db.commit_count, 1)
        increment_quota.assert_called_once_with(42)
        cache_set.assert_awaited_once()
        cached_payload = cache_set.await_args.args[1]
        self.assertFalse(cached_payload["report_meta"]["force_refresh"])

    async def test_analyze_stock_model_failure_uses_local_fallback_and_records_error_only(self) -> None:
        requested_model = _model(1, name="primary")
        db = _FakeDb([requested_model])
        request = _analysis_request(force_refresh=True)
        router = AsyncMock(side_effect=RuntimeError("gateway down"))
        cache_get = AsyncMock()
        cache_set = AsyncMock()

        with patch.object(service, "check_quota_available", return_value=(True, "")):
            with patch.object(service, "_cache_get", cache_get):
                with patch.object(service, "get_stock_data", AsyncMock(return_value=_stock_data())):
                    with patch.object(service.model_router, "analyze_with_fallback", router):
                        with patch.object(service, "_cache_set", cache_set):
                            with patch.object(service, "increment_quota") as increment_quota:
                                response = await service.analyze_stock(request, _user(), db)

        self.assertEqual(response.actual_model, "local-fallback")
        self.assertEqual(response.report_meta["status"], "error")
        self.assertIn("gateway down", response.fallback_reason)
        self.assertFalse(response.cache_hit)
        self.assertEqual(len(db.added), 1)
        self.assertIsInstance(db.added[0], AIUsageLog)
        self.assertEqual(db.added[0].status, "error")
        self.assertEqual(db.added[0].total_tokens, 0)
        self.assertEqual(db.added[0].error_message, "gateway down")
        self.assertEqual(db.commit_count, 1)
        cache_get.assert_not_awaited()
        cache_set.assert_not_awaited()
        increment_quota.assert_not_called()

    async def test_batch_summary_dedupes_cache_hits_and_error_items_without_network(self) -> None:
        db = _FakeDb([_model(1)])
        request = SimpleNamespace(
            symbols=["AAA", "BBB", "AAA"],
            report_mode="summary",
            audience="normal",
            include_news=False,
            force_refresh=False,
        )
        cached_item = {
            "symbol": "AAA",
            "name": "Cached AAA",
            "summary": "cached summary",
            "batch_cache_hit": False,
            "force_refresh": True,
        }
        cache_key = MagicMock(side_effect=lambda symbol, report_mode, audience, include_news: f"cache:{symbol}")
        cache_get = AsyncMock(side_effect=lambda key, **_kwargs: dict(cached_item) if key == "cache:AAA" else None)
        get_stock_data = AsyncMock(side_effect=RuntimeError("source down"))
        cache_set = AsyncMock()

        with patch.object(service, "batch_item_cache_key", cache_key):
            with patch.object(service, "_cache_get", cache_get):
                with patch.object(service, "get_stock_data", get_stock_data):
                    with patch.object(service, "_cache_set", cache_set):
                        result = await service.batch_summary(request, _user(), db)

        self.assertEqual(result["count"], 2)
        self.assertEqual([item["symbol"] for item in result["items"]], ["AAA", "BBB"])
        self.assertTrue(result["items"][0]["batch_cache_hit"])
        self.assertFalse(result["items"][0]["force_refresh"])
        self.assertEqual(result["items"][1]["model_status"], "error")
        self.assertIn("source down", result["items"][1]["change_alerts"][0]["message"])
        self.assertEqual([call.args[0] for call in cache_key.call_args_list], ["AAA", "BBB"])
        self.assertEqual(cache_get.await_count, 2)
        get_stock_data.assert_awaited_once_with("BBB", include_news=False)
        cache_set.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
