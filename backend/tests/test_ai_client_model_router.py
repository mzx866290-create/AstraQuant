from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.services.analysis_service.engine.ai_client import AIClient
from backend.services.analysis_service.engine.model_router import ModelHealthChecker, ModelRouter


def _model(
    model_id: int,
    *,
    name: str = "model",
    provider: str = "openai",
    external_id: str = "gpt-4o-mini",
    config: dict | None = None,
    allowed_roles: str | None = "free,premium,admin",
    sort_order: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=model_id,
        name=name,
        provider=provider,
        model_id=external_id,
        api_key_encrypted=f"encrypted-{model_id}",
        api_base_url=None,
        config=config,
        allowed_roles=allowed_roles,
        sort_order=sort_order,
    )


class _FakeQuery:
    def __init__(self, models: list[SimpleNamespace]) -> None:
        self.models = models

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        self.models = sorted(self.models, key=lambda m: (m.sort_order, m.id))
        return self

    def all(self):
        return self.models


class _FakeDb:
    def __init__(self, models: list[SimpleNamespace]) -> None:
        self.models = models

    def query(self, *_args, **_kwargs):
        return _FakeQuery(list(self.models))


class AIClientTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_api_base_url_appends_v1_once(self) -> None:
        self.assertIsNone(AIClient._normalize_api_base_url(None))
        self.assertEqual(AIClient._normalize_api_base_url("https://unit.test"), "https://unit.test/v1")
        self.assertEqual(AIClient._normalize_api_base_url("https://unit.test/v1/"), "https://unit.test/v1")

    def test_parse_openai_response_handles_dict_json_plain_text_and_objects(self) -> None:
        client = AIClient()

        parsed_dict = client._parse_openai_response(
            {"choices": [{"message": {"content": "dict ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}
        )
        parsed_json = client._parse_openai_response(
            '{"choices":[{"message":{"content":"json ok"}}],"usage":{"prompt_tokens":4,"completion_tokens":5,"total_tokens":9}}'
        )
        parsed_text = client._parse_openai_response("plain response")
        parsed_object = client._parse_openai_response(
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="object ok"))],
                usage=SimpleNamespace(prompt_tokens=6, completion_tokens=7, total_tokens=13),
            )
        )

        self.assertEqual(parsed_dict["content"], "dict ok")
        self.assertEqual(parsed_json["total_tokens"], 9)
        self.assertEqual(parsed_text["content"], "plain response")
        self.assertEqual(parsed_object["completion_tokens"], 7)

    async def test_analyze_routes_openai_deepseek_models_to_deepseek_client(self) -> None:
        client = AIClient()

        with patch.object(client, "_call_deepseek", new=AsyncMock(return_value={"content": "ok", "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})) as deepseek:
            with patch.object(client, "_call_openai", new=AsyncMock()) as openai:
                result = await client.analyze(
                    provider="openai",
                    model_id=" deepseek-chat ",
                    api_key="key",
                    api_base_url=None,
                    config={"temperature": 0.2},
                    system_prompt="sys",
                    user_prompt="user",
                )

        deepseek.assert_awaited_once()
        openai.assert_not_called()
        self.assertEqual(result["content"], "ok")
        self.assertEqual(result["total_tokens"], 150)
        self.assertIn("response_time_ms", result)

    async def test_analyze_wraps_unsupported_provider_errors(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            await AIClient().analyze("bad-provider", "m", "key", None, {}, "sys", "user")

        self.assertIn("bad-provider", str(ctx.exception))

    async def test_call_openai_uses_config_env_and_normalized_base_url(self) -> None:
        captured: dict = {}

        class _FakeCompletions:
            async def create(self, **kwargs):
                captured["create"] = kwargs
                return {"choices": [{"message": {"content": "created"}}], "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}}

        class _FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                captured["client"] = kwargs
                self.chat = SimpleNamespace(completions=_FakeCompletions())

        fake_openai_module = types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI)
        with patch.dict(sys.modules, {"openai": fake_openai_module}):
            with patch.dict("os.environ", {"AI_MAX_TOKENS": "777", "AI_REQUEST_TIMEOUT": "33", "AI_MAX_RETRIES": "4"}):
                result = await AIClient()._call_openai(
                    " gpt-4o-mini ",
                    "unit-key",
                    "https://unit.test/",
                    {"temperature": 0.9},
                    "system",
                    "user",
                )

        self.assertEqual(captured["client"]["base_url"], "https://unit.test/v1")
        self.assertEqual(captured["client"]["timeout"], 33.0)
        self.assertEqual(captured["client"]["max_retries"], 4)
        self.assertEqual(captured["create"]["model"], "gpt-4o-mini")
        self.assertEqual(captured["create"]["temperature"], 0.9)
        self.assertEqual(captured["create"]["max_tokens"], 777)
        self.assertEqual(result["content"], "created")

    async def test_custom_provider_requires_base_url(self) -> None:
        with self.assertRaises(ValueError):
            await AIClient()._call_custom("m", "key", None, {}, "sys", "user")

    def test_estimate_cost_uses_known_and_default_pricing(self) -> None:
        client = AIClient()

        self.assertEqual(client._estimate_cost("openai", "gpt-4o-mini", 1_000_000, 1_000_000), 0.75)
        self.assertEqual(client._estimate_cost("custom", "unknown", 1_000_000, 1_000_000), 3.0)


class ModelHealthCheckerTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_cached_loads_cache_and_mark_error_truncates_message(self) -> None:
        checker = ModelHealthChecker()
        fake_cache = SimpleNamespace(get=AsyncMock(return_value={"status": "healthy", "latency_ms": 12}), set=AsyncMock())

        async def fake_cache_manager():
            return fake_cache

        with patch("backend.services.analysis_service.engine.model_router.get_cache_manager", fake_cache_manager):
            cached = await checker.get_cached(9)

        self.assertEqual(cached["status"], "healthy")
        self.assertEqual(cached["latency_ms"], 12)

        checker.mark_error(9, "x" * 600)
        errored = checker.get(9)
        self.assertEqual(errored["status"], "unhealthy")
        self.assertEqual(len(errored["error"]), 500)

    async def test_probe_marks_success_and_error_without_real_model_call(self) -> None:
        checker = ModelHealthChecker()
        model = _model(1, config={"temperature": 0.8})
        ok_client = SimpleNamespace(analyze=AsyncMock(return_value={"response_time_ms": 44}))

        with patch("backend.services.analysis_service.engine.model_router.decrypt_api_key", return_value="plain-key"):
            with patch.object(checker, "_persist", new=AsyncMock()):
                healthy = await checker.probe(model, ok_client)

        self.assertEqual(healthy["status"], "healthy")
        self.assertEqual(healthy["latency_ms"], 44)
        ok_client.analyze.assert_awaited_once()
        self.assertEqual(ok_client.analyze.await_args.kwargs["config"]["max_retries"], 0)

        failing = ModelHealthChecker()
        bad_client = SimpleNamespace(analyze=AsyncMock(side_effect=RuntimeError("gateway down")))
        with patch("backend.services.analysis_service.engine.model_router.decrypt_api_key", return_value="plain-key"):
            with patch.object(failing, "_persist", new=AsyncMock()):
                unhealthy = await failing.probe(model, bad_client, analysis_grade=True)

        self.assertEqual(unhealthy["status"], "unhealthy")
        self.assertIn("gateway down", unhealthy["error"])


class ModelRouterTests(unittest.IsolatedAsyncioTestCase):
    def test_allowed_defaults_to_all_standard_roles_and_honors_explicit_roles(self) -> None:
        router = ModelRouter(ModelHealthChecker())

        self.assertTrue(router.allowed(_model(1, allowed_roles=None), SimpleNamespace(role="free")))
        self.assertTrue(router.allowed(_model(2, allowed_roles="premium,admin"), SimpleNamespace(role="admin")))
        self.assertFalse(router.allowed(_model(3, allowed_roles="premium"), SimpleNamespace(role="free")))
        self.assertTrue(router.allowed(_model(4, allowed_roles="free"), SimpleNamespace(role=None)))

    def test_candidates_put_requested_model_first_then_allowed_sorted_models(self) -> None:
        requested = _model(3, name="requested", sort_order=10)
        first = _model(1, name="first", sort_order=1)
        premium_only = _model(2, name="premium", allowed_roles="premium", sort_order=2)
        second = _model(4, name="second", sort_order=3)

        router = ModelRouter(ModelHealthChecker())
        candidates = router.candidates(_FakeDb([second, premium_only, requested, first]), requested, SimpleNamespace(role="free"))

        self.assertEqual([m.id for m in candidates], [3, 1, 4])

    async def test_analyze_with_fallback_merges_config_marks_health_and_reports_reason(self) -> None:
        requested = _model(1, name="primary", config={"temperature": 0.1, "timeout": 5}, sort_order=1)
        fallback = _model(2, name="fallback", config={"temperature": 0.2, "max_tokens": 100}, sort_order=2)
        health = ModelHealthChecker()
        router = ModelRouter(health)
        client = SimpleNamespace(
            analyze=AsyncMock(
                side_effect=[
                    RuntimeError("primary timeout"),
                    {"content": "fallback ok", "response_time_ms": 55},
                ]
            )
        )

        with patch("backend.services.analysis_service.engine.model_router.decrypt_api_key", side_effect=lambda value: f"plain-{value}"):
            with patch.object(health, "_persist", new=AsyncMock()):
                result, used_model, reason = await router.analyze_with_fallback(
                    db=_FakeDb([requested, fallback]),
                    requested_model=requested,
                    user=SimpleNamespace(role="free"),
                    ai_client=client,
                    config={"temperature": 0.7},
                    system_prompt="sys",
                    user_prompt="user",
                )

        self.assertEqual(result["content"], "fallback ok")
        self.assertEqual(used_model.id, 2)
        self.assertIn("primary timeout", reason)
        first_call, second_call = client.analyze.await_args_list
        self.assertEqual(first_call.kwargs["config"], {"temperature": 0.7, "timeout": 5})
        self.assertEqual(second_call.kwargs["config"], {"temperature": 0.7, "max_tokens": 100})
        self.assertEqual(health.get(1)["status"], "unhealthy")
        self.assertEqual(health.get(2)["status"], "healthy")

    async def test_analyze_with_fallback_skips_unhealthy_fallback_but_tries_requested(self) -> None:
        requested = _model(1, name="primary", sort_order=1)
        unhealthy_fallback = _model(2, name="bad fallback", sort_order=2)
        healthy_fallback = _model(3, name="good fallback", sort_order=3)
        health = ModelHealthChecker()
        health.mark_error(1, "old primary error")
        health.mark_error(2, "old fallback error")
        router = ModelRouter(health)
        client = SimpleNamespace(analyze=AsyncMock(side_effect=[RuntimeError("new primary error"), {"content": "ok", "response_time_ms": 7}]))

        with patch("backend.services.analysis_service.engine.model_router.decrypt_api_key", return_value="plain-key"):
            with patch.object(health, "_persist", new=AsyncMock()):
                result, used_model, reason = await router.analyze_with_fallback(
                    db=_FakeDb([requested, unhealthy_fallback, healthy_fallback]),
                    requested_model=requested,
                    user=SimpleNamespace(role="free"),
                    ai_client=client,
                    config={},
                    system_prompt="sys",
                    user_prompt="user",
                )

        self.assertEqual(result["content"], "ok")
        self.assertEqual(used_model.id, 3)
        self.assertEqual(client.analyze.await_count, 2)
        self.assertIn("new primary error", reason)

    async def test_analyze_with_fallback_raises_aggregated_errors_when_all_models_fail(self) -> None:
        requested = _model(1, name="primary", sort_order=1)
        fallback = _model(2, name="fallback", sort_order=2)
        health = ModelHealthChecker()
        router = ModelRouter(health)
        client = SimpleNamespace(analyze=AsyncMock(side_effect=[RuntimeError("timeout"), RuntimeError("quota")]))

        with patch("backend.services.analysis_service.engine.model_router.decrypt_api_key", return_value="plain-key"):
            with patch.object(health, "_persist", new=AsyncMock()):
                with self.assertRaises(RuntimeError) as ctx:
                    await router.analyze_with_fallback(
                        db=_FakeDb([requested, fallback]),
                        requested_model=requested,
                        user=SimpleNamespace(role="free"),
                        ai_client=client,
                        config={},
                        system_prompt="sys",
                        user_prompt="user",
                    )

        self.assertIn("primary: timeout", str(ctx.exception))
        self.assertIn("fallback: quota", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
