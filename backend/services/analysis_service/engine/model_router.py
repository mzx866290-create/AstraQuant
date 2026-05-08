from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any

from backend.shared.auth import decrypt_api_key
from backend.shared.cache import get_cache_manager
from backend.shared.models import AIModel, User


@dataclass
class ModelHealth:
    model_id: int
    status: str
    latency_ms: int | None = None
    checked_at: str | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at,
            "error": self.error,
        }


class ModelHealthChecker:
    """In-process model health registry with optional live probing."""

    def __init__(self) -> None:
        self._health: dict[int, ModelHealth] = {}

    def get(self, model_id: int) -> dict:
        return self._health.get(model_id, ModelHealth(model_id=model_id, status="unknown")).as_dict()

    async def get_cached(self, model_id: int) -> dict:
        if model_id in self._health:
            return self.get(model_id)
        try:
            cache = await get_cache_manager()
            cached = await cache.get("ai_model_health", model_id)
            if cached:
                self._health[model_id] = ModelHealth(
                    model_id=model_id,
                    status=cached.get("status", "unknown"),
                    latency_ms=cached.get("latency_ms"),
                    checked_at=cached.get("checked_at"),
                    error=cached.get("error"),
                )
                return self.get(model_id)
        except Exception:
            pass
        return self.get(model_id)

    def mark_success(self, model_id: int, latency_ms: int | None = None) -> None:
        self._health[model_id] = ModelHealth(
            model_id=model_id,
            status="healthy",
            latency_ms=latency_ms,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    async def mark_success_async(self, model_id: int, latency_ms: int | None = None) -> None:
        self.mark_success(model_id, latency_ms)
        await self._persist(model_id)

    def mark_error(self, model_id: int, error: str) -> None:
        self._health[model_id] = ModelHealth(
            model_id=model_id,
            status="unhealthy",
            checked_at=datetime.now(timezone.utc).isoformat(),
            error=error[:500],
        )

    async def mark_error_async(self, model_id: int, error: str) -> None:
        self.mark_error(model_id, error)
        await self._persist(model_id)

    async def _persist(self, model_id: int) -> None:
        try:
            cache = await get_cache_manager()
            await cache.set("ai_model_health", model_id, value=self.get(model_id))
        except Exception:
            pass

    async def probe(self, model: AIModel, ai_client: Any, analysis_grade: bool = False) -> dict:
        prompt = (
            "In two short Chinese sentences, assess A-share data quality risk. "
            "Data: price 34.5, PE 21, five K-line rows, mostly neutral news but one high-impact negative item."
            if analysis_grade
            else "Reply in Chinese only: model available."
        )
        config = dict(model.config or {})
        config.update({"temperature": 0.1, "timeout": 20 if analysis_grade else 12, "max_retries": 0, "max_tokens": 180})
        start = time.time()
        try:
            result = await ai_client.analyze(
                provider=model.provider,
                model_id=model.model_id,
                api_key=decrypt_api_key(model.api_key_encrypted),
                api_base_url=model.api_base_url,
                config=config,
                system_prompt="You are a model health checker. Reply briefly in Chinese.",
                user_prompt=prompt,
            )
            latency_ms = result.get("response_time_ms") or int((time.time() - start) * 1000)
            await self.mark_success_async(model.id, latency_ms)
        except Exception as exc:
            await self.mark_error_async(model.id, str(exc))
        return await self.get_cached(model.id)


class ModelRouter:
    def __init__(self, health_checker: ModelHealthChecker) -> None:
        self.health_checker = health_checker

    @staticmethod
    def allowed(model: AIModel, user: User) -> bool:
        allowed_roles = model.allowed_roles.split(",") if model.allowed_roles else ["free", "premium", "admin"]
        return (user.role or "free") in allowed_roles

    def candidates(self, db, requested_model: AIModel, user: User) -> list[AIModel]:
        models = (
            db.query(AIModel)
            .filter(AIModel.is_active == True)
            .order_by(AIModel.sort_order, AIModel.id)
            .all()
        )
        allowed = [m for m in models if self.allowed(m, user)]
        ordered = [requested_model] + [m for m in allowed if m.id != requested_model.id]
        return ordered

    async def analyze_with_fallback(
        self,
        *,
        db,
        requested_model: AIModel,
        user: User,
        ai_client: Any,
        config: dict,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[dict, AIModel, str | None]:
        errors: list[str] = []
        for model in self.candidates(db, requested_model, user):
            health = await self.health_checker.get_cached(model.id)
            if model.id != requested_model.id and health.get("status") == "unhealthy":
                continue
            try:
                model_config = dict(model.config or {})
                model_config.update(config)
                result = await ai_client.analyze(
                    provider=model.provider,
                    model_id=model.model_id,
                    api_key=decrypt_api_key(model.api_key_encrypted),
                    api_base_url=model.api_base_url,
                    config=model_config,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
                await self.health_checker.mark_success_async(model.id, result.get("response_time_ms"))
                fallback_reason = None
                if model.id != requested_model.id:
                    fallback_reason = "; ".join(errors) or "requested model failed"
                return result, model, fallback_reason
            except Exception as exc:
                message = f"{model.name}: {exc}"
                errors.append(message[:300])
                await self.health_checker.mark_error_async(model.id, str(exc))
        raise RuntimeError("; ".join(errors) or "no usable AI model")


model_health_checker = ModelHealthChecker()
model_router = ModelRouter(model_health_checker)
