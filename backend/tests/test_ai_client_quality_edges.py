from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.services.analysis_service.engine.ai_client import AIClient


class AIClientQualityEdgeTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_api_base_url_handles_missing_trailing_and_existing_v1(self) -> None:
        cases = [
            (None, None),
            ("", ""),
            ("https://unit.test", "https://unit.test/v1"),
            ("https://unit.test/", "https://unit.test/v1"),
            ("https://unit.test/v1", "https://unit.test/v1"),
            ("https://unit.test/v1/", "https://unit.test/v1"),
            ("https://unit.test/openai", "https://unit.test/openai/v1"),
        ]

        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(AIClient._normalize_api_base_url(raw), expected)

    def test_parse_openai_response_accepts_json_dict_plain_text_and_object_shapes(self) -> None:
        client = AIClient()

        parsed_json = client._parse_openai_response(
            '{"choices":[{"message":{"content":"json ok"}}],"usage":{"prompt_tokens":4,"completion_tokens":5,"total_tokens":9}}'
        )
        parsed_dict = client._parse_openai_response(
            {
                "choices": [{"message": {"content": "dict ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            }
        )
        parsed_text = client._parse_openai_response("plain text reply")
        parsed_object = client._parse_openai_response(
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="object ok"))],
                usage=SimpleNamespace(prompt_tokens=6, completion_tokens=7, total_tokens=13),
            )
        )

        self.assertEqual(
            parsed_json,
            {"content": "json ok", "prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
        )
        self.assertEqual(
            parsed_dict,
            {"content": "dict ok", "prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        )
        self.assertEqual(
            parsed_text,
            {"content": "plain text reply", "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        self.assertEqual(
            parsed_object,
            {"content": "object ok", "prompt_tokens": 6, "completion_tokens": 7, "total_tokens": 13},
        )

    def test_estimate_cost_uses_known_model_prices_and_default_fallback(self) -> None:
        client = AIClient()

        self.assertEqual(client._estimate_cost("openai", "gpt-4o-mini", 1_000_000, 1_000_000), 0.75)
        self.assertEqual(client._estimate_cost("deepseek", "deepseek-chat", 1_000_000, 1_000_000), 1.37)
        self.assertEqual(client._estimate_cost("openai", "unknown-model", 1_000_000, 1_000_000), 3.0)
        self.assertEqual(client._estimate_cost("custom", "anything", 250_000, 125_000), 0.5)

    async def test_analyze_routes_provider_branches_to_expected_private_call(self) -> None:
        cases = [
            ("openai", "gpt-4o-mini", "_call_openai"),
            ("custom", "custom-model", "_call_custom"),
            ("deepseek", "deepseek-chat", "_call_deepseek"),
            ("anthropic", "claude-3-haiku-20240307", "_call_anthropic"),
        ]

        for provider, model_id, expected_method in cases:
            with self.subTest(provider=provider):
                client = AIClient()
                payload = {
                    "content": f"{provider} ok",
                    "prompt_tokens": 1_000,
                    "completion_tokens": 500,
                    "total_tokens": 1_500,
                }
                with patch.object(client, "_call_openai", new=AsyncMock(return_value=payload)) as call_openai:
                    with patch.object(client, "_call_custom", new=AsyncMock(return_value=payload)) as call_custom:
                        with patch.object(client, "_call_deepseek", new=AsyncMock(return_value=payload)) as call_deepseek:
                            with patch.object(client, "_call_anthropic", new=AsyncMock(return_value=payload)) as call_anthropic:
                                result = await client.analyze(
                                    provider=provider,
                                    model_id=model_id,
                                    api_key="unit-key",
                                    api_base_url="https://unit.test",
                                    config={"temperature": 0.2},
                                    system_prompt="system",
                                    user_prompt="user",
                                )

                calls = {
                    "_call_openai": call_openai,
                    "_call_custom": call_custom,
                    "_call_deepseek": call_deepseek,
                    "_call_anthropic": call_anthropic,
                }
                calls[expected_method].assert_awaited_once()
                for name, mocked in calls.items():
                    if name != expected_method:
                        mocked.assert_not_called()
                self.assertEqual(result["content"], f"{provider} ok")
                self.assertEqual(result["total_tokens"], 1_500)
                self.assertIn("response_time_ms", result)

    async def test_analyze_openai_provider_uses_stripped_model_id_for_deepseek_routing(self) -> None:
        client = AIClient()
        payload = {"content": "deepseek ok", "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

        with patch.object(client, "_call_deepseek", new=AsyncMock(return_value=payload)) as call_deepseek:
            with patch.object(client, "_call_openai", new=AsyncMock(return_value=payload)) as call_openai:
                result = await client.analyze(
                    provider="openai",
                    model_id=" deepseek-chat ",
                    api_key="unit-key",
                    api_base_url=None,
                    config={},
                    system_prompt="system",
                    user_prompt="user",
                )

        call_deepseek.assert_awaited_once()
        call_openai.assert_not_called()
        self.assertEqual(call_deepseek.await_args.args[0], " deepseek-chat ")
        self.assertEqual(result["content"], "deepseek ok")

    async def test_analyze_wraps_unsupported_provider_with_runtime_error(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            await AIClient().analyze(
                provider="unsupported",
                model_id="model",
                api_key="unit-key",
                api_base_url=None,
                config={},
                system_prompt="system",
                user_prompt="user",
            )

        self.assertIsInstance(ctx.exception.__cause__, ValueError)
        self.assertIn("unsupported", str(ctx.exception))

    async def test_call_custom_requires_api_base_url(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await AIClient()._call_custom(
                model_id="custom-model",
                api_key="unit-key",
                api_base_url=None,
                config={},
                system_prompt="system",
                user_prompt="user",
            )

        self.assertIn("api_base_url", str(ctx.exception))

    async def test_call_deepseek_reuses_openai_call_with_deepseek_base_url(self) -> None:
        client = AIClient()
        payload = {"content": "ok", "prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}

        with patch.object(client, "_call_openai", new=AsyncMock(return_value=payload)) as call_openai:
            default_result = await client._call_deepseek(
                "deepseek-chat", "unit-key", None, {"max_tokens": 10}, "system", "user"
            )
            custom_result = await client._call_deepseek(
                "deepseek-chat", "unit-key", "https://deepseek.unit/api", {}, "system", "user"
            )

        self.assertEqual(default_result, payload)
        self.assertEqual(custom_result, payload)
        self.assertEqual(call_openai.await_count, 2)
        self.assertEqual(call_openai.await_args_list[0].args[2], "https://api.deepseek.com")
        self.assertEqual(call_openai.await_args_list[1].args[2], "https://deepseek.unit/api")

    async def test_call_openai_normalizes_base_url_and_strips_model_before_sdk_call(self) -> None:
        captured: dict[str, dict] = {}

        class _FakeCompletions:
            async def create(self, **kwargs):
                captured["create"] = kwargs
                return {
                    "choices": [{"message": {"content": "created"}}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
                }

        class _FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                captured["client"] = kwargs
                self.chat = SimpleNamespace(completions=_FakeCompletions())

        fake_openai_module = types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI)

        with patch.dict(sys.modules, {"openai": fake_openai_module}):
            result = await AIClient()._call_openai(
                model_id=" gpt-4o-mini ",
                api_key="unit-key",
                api_base_url="https://unit.test/api/",
                config={"temperature": 0.6, "max_tokens": 321, "timeout": 9, "max_retries": 0},
                system_prompt="system",
                user_prompt="user",
            )

        self.assertEqual(captured["client"]["api_key"], "unit-key")
        self.assertEqual(captured["client"]["base_url"], "https://unit.test/api/v1")
        self.assertEqual(captured["client"]["timeout"], 9.0)
        self.assertEqual(captured["client"]["max_retries"], 0)
        self.assertEqual(captured["create"]["model"], "gpt-4o-mini")
        self.assertEqual(captured["create"]["temperature"], 0.6)
        self.assertEqual(captured["create"]["max_tokens"], 321)
        self.assertEqual(
            captured["create"]["messages"],
            [{"role": "system", "content": "system"}, {"role": "user", "content": "user"}],
        )
        self.assertEqual(result["content"], "created")


if __name__ == "__main__":
    unittest.main()
