"""
AI 模型调用客户端
支持 OpenAI / Anthropic / DeepSeek / Custom
"""
import asyncio
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AIClient:
    """统一的 AI 模型调用客户端"""

    def __init__(self):
        self._clients: Dict[str, Any] = {}

    async def analyze(
        self,
        provider: str,
        model_id: str,
        api_key: str,
        api_base_url: Optional[str],
        config: Optional[dict],
        system_prompt: str,
        user_prompt: str,
    ) -> dict:
        """
        调用 AI 模型进行分析

        返回: {
            "content": str,           # AI 回复内容
            "prompt_tokens": int,     # 输入 token 数
            "completion_tokens": int,  # 输出 token 数
            "total_tokens": int,      # 总 token 数
            "cost": float,            # 预估费用 (USD)
            "response_time_ms": int,  # 响应时间
        }
        """
        start_time = time.time()
        extra_headers = {}

        try:
            if provider == "openai":
                result = await self._call_openai(model_id, api_key, api_base_url, config, system_prompt, user_prompt)
            elif provider == "anthropic":
                result = await self._call_anthropic(model_id, api_key, config, system_prompt, user_prompt)
            elif provider == "deepseek":
                result = await self._call_deepseek(model_id, api_key, api_base_url, config, system_prompt, user_prompt)
            elif provider == "custom":
                result = await self._call_custom(model_id, api_key, api_base_url, config, system_prompt, user_prompt)
            else:
                raise ValueError(f"不支持的 provider: {provider}")

            elapsed = int((time.time() - start_time) * 1000)

            # 计算费用 (简化估算)
            cost = self._estimate_cost(provider, model_id, result.get("prompt_tokens", 0), result.get("completion_tokens", 0))

            return {
                "content": result.get("content", ""),
                "prompt_tokens": result.get("prompt_tokens", 0),
                "completion_tokens": result.get("completion_tokens", 0),
                "total_tokens": result.get("total_tokens", 0),
                "cost": cost,
                "response_time_ms": elapsed,
            }

        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            logger.error(f"AI 调用失败: {e}")
            raise RuntimeError(f"AI 调用失败: {str(e)}") from e

    async def _call_openai(
        self,
        model_id: str,
        api_key: str,
        api_base_url: Optional[str],
        config: Optional[dict],
        system_prompt: str,
        user_prompt: str,
    ) -> dict:
        """调用 OpenAI API (GPT-4o 等)"""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key, base_url=api_base_url)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # 获取参数
        temperature = config.get("temperature", 0.7) if config else 0.7
        max_tokens = config.get("max_tokens", 4096) if config else 4096

        response = await client.chat.completions.create(
            model=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return {
            "content": response.choices[0].message.content or "",
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    async def _call_anthropic(
        self,
        model_id: str,
        api_key: str,
        config: Optional[dict],
        system_prompt: str,
        user_prompt: str,
    ) -> dict:
        """调用 Anthropic API (Claude 3.5/4 等)"""
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)

        # 获取参数
        temperature = config.get("temperature", 0.7) if config else 0.7
        max_tokens = config.get("max_tokens", 4096) if config else 4096

        response = await client.messages.create(
            model=model_id,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return {
            "content": response.content[0].text if response.content else "",
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }

    async def _call_deepseek(
        self,
        model_id: str,
        api_key: str,
        api_base_url: Optional[str],
        config: Optional[dict],
        system_prompt: str,
        user_prompt: str,
    ) -> dict:
        """调用 DeepSeek API"""
        base_url = api_base_url or "https://api.deepseek.com"
        return await self._call_openai(model_id, api_key, base_url, config, system_prompt, user_prompt)

    async def _call_custom(
        self,
        model_id: str,
        api_key: str,
        api_base_url: Optional[str],
        config: Optional[dict],
        system_prompt: str,
        user_prompt: str,
    ) -> dict:
        """调用自定义 API (兼容 OpenAI 格式)"""
        if not api_base_url:
            raise ValueError("custom provider 需要提供 api_base_url")
        return await self._call_openai(model_id, api_key, api_base_url, config, system_prompt, user_prompt)

    def _estimate_cost(self, provider: str, model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
        """估算费用 (USD) - 基于公开定价"""
        # $ per 1M tokens
        pricing = {
            "openai": {
                "gpt-4o": {"input": 5.0, "output": 15.0},
                "gpt-4o-mini": {"input": 0.15, "output": 0.60},
                "gpt-4-turbo": {"input": 10.0, "output": 30.0},
                "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
            },
            "anthropic": {
                "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
                "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
                "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
                "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
            },
            "deepseek": {
                "deepseek-chat": {"input": 0.27, "output": 1.1},
                "deepseek-coder": {"input": 0.27, "output": 1.1},
            },
        }

        provider_pricing = pricing.get(provider, {})
        model_pricing = provider_pricing.get(model_id, {"input": 1.0, "output": 2.0})

        input_cost = (prompt_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * model_pricing["output"]

        return round(input_cost + output_cost, 6)


# 全局 AI 客户端实例
ai_client = AIClient()