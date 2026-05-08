from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.analysis_service.engine.model_router import (
    ModelHealth,
    ModelHealthChecker,
    ModelRouter,
)


def _model(
    model_id: int,
    *,
    name: str | None = None,
    provider: str = "openai",
    external_id: str | None = None,
    config: dict | None = None,
    allowed_roles: str | None = "free,premium,admin",
    sort_order: int = 0,
    api_base_url: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=model_id,
        name=name or f"model-{model_id}",
        provider=provider,
        model_id=external_id or f"external-{model_id}",
        api_key_encrypted=f"encrypted-{model_id}",
        api_base_url=api_base_url,
        config=config,
        allowed_roles=allowed_roles,
        sort_order=sort_order,
    )


def _user(role: str | None = "free") -> SimpleNamespace:
    return SimpleNamespace(role=role)


class _FakeCache:
    def __init__(self, data: dict | None = None, *, fail_get: bool = False, fail_set: bool = False) -> None:
        self.data = data or {}
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.get_calls: list[tuple[str, int]] = []
        self.set_calls: list[tuple[str, int, dict]] = []

    async def get(self, category: str, model_id: int):
        self.get_calls.append((category, model_id))
        if self.fail_get:
            raise RuntimeError("cache read unavailable")
        return self.data.get((category, model_id))

    async def set(self, category: str, model_id: int, *, value: dict):
        self.set_calls.append((category, model_id, value))
        if self.fail_set:
            raise RuntimeError("cache write unavailable")
        self.data[(category, model_id)] = value


class _FakeQuery:
    def __init__(self, models: list[SimpleNamespace]) -> None:
        self.models = models

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        self.models = sorted(self.models, key=lambda model: (model.sort_order, model.id))
        return self

    def all(self):
        return list(self.models)


class _FakeDb:
    def __init__(self, models: list[SimpleNamespace]) -> None:
        self.models = models

    def query(self, *_args, **_kwargs):
        return _FakeQuery(list(self.models))


def _cache_manager_returning(cache: _FakeCache):
    async def fake_get_cache_manager():
        return cache

    return fake_get_cache_manager


class ModelHealthQualityTests(unittest.IsolatedAsyncioTestCase):
    def test_model_health_as_dict_preserves_all_fields(self) -> None:
        health = ModelHealth(
            model_id=12,
            status="healthy",
            latency_ms=34,
            checked_at="2026-05-07T10:00:00+00:00",
            error="none",
        )

        self.assertEqual(
            health.as_dict(),
            {
                "model_id": 12,
                "status": "healthy",
                "latency_ms": 34,
                "checked_at": "2026-05-07T10:00:00+00:00",
                "error": "none",
            },
        )

    def test_get_mark_success_and_mark_error_update_in_memory_health(self) -> None:
        checker = ModelHealthChecker()

        self.assertEqual(
            checker.get(77),
            {"model_id": 77, "status": "unknown", "latency_ms": None, "checked_at": None, "error": None},
        )

        checker.mark_success(77, latency_ms=123)
        healthy = checker.get(77)
        self.assertEqual(healthy["model_id"], 77)
        self.assertEqual(healthy["status"], "healthy")
        self.assertEqual(healthy["latency_ms"], 123)
        self.assertIsNotNone(healthy["checked_at"])
        self.assertIsNone(healthy["error"])

        checker.mark_error(77, "x" * 600)
        unhealthy = checker.get(77)
        self.assertEqual(unhealthy["status"], "unhealthy")
        self.assertIsNone(unhealthy["latency_ms"])
        self.assertEqual(len(unhealthy["error"]), 500)

    async def test_get_cached_returns_memory_hit_without_touching_cache(self) -> None:
        checker = ModelHealthChecker()
        checker.mark_success(5, latency_ms=88)
        cache = _FakeCache(data={("ai_model_health", 5): {"status": "unhealthy", "error": "stale"}})

        with patch("backend.services.analysis_service.engine.model_router.get_cache_manager", new=_cache_manager_returning(cache)):
            result = await checker.get_cached(5)

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["latency_ms"], 88)
        self.assertEqual(cache.get_calls, [])

    async def test_get_cached_hydrates_from_cache_hit(self) -> None:
        checker = ModelHealthChecker()
        cache = _FakeCache(
            data={
                ("ai_model_health", 9): {
                    "status": "healthy",
                    "latency_ms": 41,
                    "checked_at": "cached-time",
                    "error": None,
                }
            }
        )

        with patch("backend.services.analysis_service.engine.model_router.get_cache_manager", new=_cache_manager_returning(cache)):
            result = await checker.get_cached(9)

        self.assertEqual(result["model_id"], 9)
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["latency_ms"], 41)
        self.assertEqual(result["checked_at"], "cached-time")
        self.assertEqual(checker.get(9), result)
        self.assertEqual(cache.get_calls, [("ai_model_health", 9)])

    async def test_get_cached_returns_unknown_when_cache_raises(self) -> None:
        checker = ModelHealthChecker()
        cache = _FakeCache(fail_get=True)

        with patch("backend.services.analysis_service.engine.model_router.get_cache_manager", new=_cache_manager_returning(cache)):
            result = await checker.get_cached(10)

        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["model_id"], 10)
        self.assertEqual(cache.get_calls, [("ai_model_health", 10)])

    async def test_mark_success_async_and_mark_error_async_persist_and_swallow_cache_failures(self) -> None:
        checker = ModelHealthChecker()
        cache = _FakeCache()

        with patch("backend.services.analysis_service.engine.model_router.get_cache_manager", new=_cache_manager_returning(cache)):
            await checker.mark_success_async(1, latency_ms=25)
            await checker.mark_error_async(2, "gateway down")

        self.assertEqual(len(cache.set_calls), 2)
        self.assertEqual(cache.set_calls[0][0:2], ("ai_model_health", 1))
        self.assertEqual(cache.set_calls[0][2]["status"], "healthy")
        self.assertEqual(cache.set_calls[0][2]["latency_ms"], 25)
        self.assertEqual(cache.set_calls[1][0:2], ("ai_model_health", 2))
        self.assertEqual(cache.set_calls[1][2]["status"], "unhealthy")
        self.assertEqual(cache.set_calls[1][2]["error"], "gateway down")

        failing_cache = _FakeCache(fail_set=True)
        with patch("backend.services.analysis_service.engine.model_router.get_cache_manager", new=_cache_manager_returning(failing_cache)):
            await checker.mark_success_async(3, latency_ms=5)

        self.assertEqual(checker.get(3)["status"], "healthy")
        self.assertEqual(failing_cache.set_calls[0][0:2], ("ai_model_health", 3))

    async def test_probe_success_uses_decrypted_key_and_persists_healthy_status(self) -> None:
        checker = ModelHealthChecker()
        cache = _FakeCache()
        model = _model(
            31,
            provider="custom",
            external_id="quality-model",
            config={"temperature": 0.9, "custom": "kept"},
            api_base_url="https://unit.test/v1",
        )
        client = SimpleNamespace(analyze=AsyncMock(return_value={"content": "ok", "response_time_ms": 64}))

        with patch("backend.services.analysis_service.engine.model_router.decrypt_api_key", return_value="plain-key"):
            with patch("backend.services.analysis_service.engine.model_router.get_cache_manager", new=_cache_manager_returning(cache)):
                result = await checker.probe(model, client, analysis_grade=True)

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["latency_ms"], 64)
        client.analyze.assert_awaited_once()
        call = client.analyze.await_args.kwargs
        self.assertEqual(call["provider"], "custom")
        self.assertEqual(call["model_id"], "quality-model")
        self.assertEqual(call["api_key"], "plain-key")
        self.assertEqual(call["api_base_url"], "https://unit.test/v1")
        self.assertEqual(call["config"]["temperature"], 0.1)
        self.assertEqual(call["config"]["timeout"], 20)
        self.assertEqual(call["config"]["max_retries"], 0)
        self.assertEqual(call["config"]["custom"], "kept")
        self.assertEqual(cache.set_calls[0][2]["status"], "healthy")

    async def test_probe_failure_marks_unhealthy_and_returns_cached_status(self) -> None:
        checker = ModelHealthChecker()
        cache = _FakeCache()
        model = _model(32)
        client = SimpleNamespace(analyze=AsyncMock(side_effect=RuntimeError("provider refused")))

        with patch("backend.services.analysis_service.engine.model_router.decrypt_api_key", return_value="plain-key"):
            with patch("backend.services.analysis_service.engine.model_router.get_cache_manager", new=_cache_manager_returning(cache)):
                result = await checker.probe(model, client)

        self.assertEqual(result["status"], "unhealthy")
        self.assertIn("provider refused", result["error"])
        self.assertEqual(cache.set_calls[0][0:2], ("ai_model_health", 32))
        self.assertEqual(cache.set_calls[0][2]["status"], "unhealthy")

    def test_allowed_defaults_to_standard_roles_and_honors_explicit_roles(self) -> None:
        self.assertTrue(ModelRouter.allowed(_model(1, allowed_roles=None), _user("free")))
        self.assertTrue(ModelRouter.allowed(_model(2, allowed_roles=None), _user("premium")))
        self.assertTrue(ModelRouter.allowed(_model(3, allowed_roles=None), _user("admin")))
        self.assertTrue(ModelRouter.allowed(_model(4, allowed_roles=None), _user(None)))
        self.assertFalse(ModelRouter.allowed(_model(5, allowed_roles=None), _user("auditor")))
        self.assertTrue(ModelRouter.allowed(_model(6, allowed_roles="premium,admin"), _user("premium")))
        self.assertFalse(ModelRouter.allowed(_model(7, allowed_roles="premium,admin"), _user("free")))

    def test_candidates_put_requested_first_then_allowed_sorted_without_duplicate(self) -> None:
        requested = _model(10, name="requested", sort_order=99)
        admin_only = _model(11, name="admin-only", allowed_roles="admin", sort_order=0)
        later = _model(12, name="later", sort_order=3)
        earlier = _model(13, name="earlier", sort_order=1)
        same_order_lower_id = _model(8, name="same-order-lower-id", sort_order=3)

        router = ModelRouter(ModelHealthChecker())
        candidates = router.candidates(
            _FakeDb([later, requested, admin_only, same_order_lower_id, earlier]),
            requested,
            _user("free"),
        )

        self.assertEqual([model.id for model in candidates], [10, 13, 8, 12])
        self.assertEqual([model.id for model in candidates].count(10), 1)

    async def test_analyze_with_fallback_skips_unhealthy_backup_but_still_tries_requested(self) -> None:
        requested = _model(21, name="primary", config={"timeout": 5}, sort_order=1)
        unhealthy_backup = _model(22, name="unhealthy backup", sort_order=2)
        healthy_backup = _model(23, name="healthy backup", sort_order=3)
        health = ModelHealthChecker()
        health.mark_error(21, "old primary incident")
        health.mark_error(22, "old backup incident")
        router = ModelRouter(health)
        client = SimpleNamespace(
            analyze=AsyncMock(side_effect=[RuntimeError("fresh primary failure"), {"content": "backup ok", "response_time_ms": 73}])
        )

        with patch("backend.services.analysis_service.engine.model_router.decrypt_api_key", return_value="plain-key"):
            with patch.object(health, "_persist", new=AsyncMock()):
                result, used_model, reason = await router.analyze_with_fallback(
                    db=_FakeDb([unhealthy_backup, healthy_backup, requested]),
                    requested_model=requested,
                    user=_user("free"),
                    ai_client=client,
                    config={"temperature": 0.4},
                    system_prompt="system",
                    user_prompt="user",
                )

        self.assertEqual(result["content"], "backup ok")
        self.assertEqual(used_model.id, 23)
        self.assertIn("primary: fresh primary failure", reason)
        self.assertEqual(client.analyze.await_count, 2)
        attempted_model_ids = [call.kwargs["model_id"] for call in client.analyze.await_args_list]
        self.assertEqual(attempted_model_ids, ["external-21", "external-23"])
        self.assertEqual(health.get(21)["status"], "unhealthy")
        self.assertEqual(health.get(22)["status"], "unhealthy")
        self.assertEqual(health.get(23)["status"], "healthy")

    async def test_analyze_with_fallback_raises_aggregated_error_when_every_attempt_fails(self) -> None:
        requested = _model(41, name="primary", sort_order=1)
        fallback = _model(42, name="fallback", sort_order=2)
        health = ModelHealthChecker()
        router = ModelRouter(health)
        client = SimpleNamespace(analyze=AsyncMock(side_effect=[RuntimeError("timeout"), RuntimeError("quota")]))

        with patch("backend.services.analysis_service.engine.model_router.decrypt_api_key", return_value="plain-key"):
            with patch.object(health, "_persist", new=AsyncMock()):
                with self.assertRaises(RuntimeError) as ctx:
                    await router.analyze_with_fallback(
                        db=_FakeDb([requested, fallback]),
                        requested_model=requested,
                        user=_user("free"),
                        ai_client=client,
                        config={},
                        system_prompt="system",
                        user_prompt="user",
                    )

        message = str(ctx.exception)
        self.assertIn("primary: timeout", message)
        self.assertIn("fallback: quota", message)
        self.assertEqual(client.analyze.await_count, 2)
        self.assertEqual(health.get(41)["status"], "unhealthy")
        self.assertEqual(health.get(42)["status"], "unhealthy")


if __name__ == "__main__":
    unittest.main()
