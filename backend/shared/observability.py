"""Health, readiness, and metrics helpers for FastAPI services."""
from __future__ import annotations

import logging
import time
from typing import Callable, Iterable

from fastapi import Response
from sqlalchemy import text

logger = logging.getLogger(__name__)

ReadyCheck = Callable[[], dict]
HTTP_REQUESTS_TOTAL = None
HTTP_REQUEST_DURATION_SECONDS = None
HTTP_REQUESTS_IN_PROGRESS = None
SERVICE_INFO = None


def _metric_path(request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", "") if route is not None else ""
    return path or request.url.path or "unknown"


def install_metrics(app, service_name: str | None = None) -> None:
    global HTTP_REQUESTS_TOTAL
    global HTTP_REQUEST_DURATION_SECONDS
    global HTTP_REQUESTS_IN_PROGRESS
    global SERVICE_INFO

    try:
        from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
    except Exception as exc:
        logger.warning("prometheus_client unavailable, /metrics disabled: %s", exc)
        return

    if getattr(app.state, "metrics_installed", False):
        return

    if HTTP_REQUESTS_TOTAL is None:
        HTTP_REQUESTS_TOTAL = Counter(
            "stock_platform_http_requests_total",
            "Total HTTP requests served by the stock platform services.",
            ("service", "method", "path", "status_code"),
        )
    if HTTP_REQUEST_DURATION_SECONDS is None:
        HTTP_REQUEST_DURATION_SECONDS = Histogram(
            "stock_platform_http_request_duration_seconds",
            "HTTP request latency in seconds for the stock platform services.",
            ("service", "method", "path"),
        )
    if HTTP_REQUESTS_IN_PROGRESS is None:
        HTTP_REQUESTS_IN_PROGRESS = Gauge(
            "stock_platform_http_requests_in_progress",
            "In-flight HTTP requests for the stock platform services.",
            ("service", "method"),
        )
    if SERVICE_INFO is None:
        SERVICE_INFO = Gauge(
            "stock_platform_service_info",
            "Static service presence marker.",
            ("service",),
        )

    resolved_service_name = service_name or getattr(app, "title", "unknown-service")
    SERVICE_INFO.labels(service=resolved_service_name).set(1)

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics():
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.middleware("http")
    async def prometheus_http_metrics(request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        request_labels = {
            "service": resolved_service_name,
            "method": method,
        }
        HTTP_REQUESTS_IN_PROGRESS.labels(**request_labels).inc()
        started_at = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            path = _metric_path(request)
            elapsed = max(time.perf_counter() - started_at, 0.0)
            HTTP_REQUESTS_TOTAL.labels(
                service=resolved_service_name,
                method=method,
                path=path,
                status_code=str(status_code),
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(
                service=resolved_service_name,
                method=method,
                path=path,
            ).observe(elapsed)
            HTTP_REQUESTS_IN_PROGRESS.labels(**request_labels).dec()

    app.state.metrics_installed = True


def database_check() -> dict:
    try:
        from backend.shared.database import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"name": "database", "status": "ok", "required": True}
    except Exception as exc:
        return {
            "name": "database",
            "status": "error",
            "required": True,
            "error": str(exc)[:180],
        }


def redis_check(required: bool = False) -> dict:
    try:
        from backend.shared.cache import redis_client

        if redis_client is None:
            return {"name": "redis", "status": "degraded", "required": required, "error": "not connected"}
        return {"name": "redis", "status": "ok", "required": required}
    except Exception as exc:
        return {
            "name": "redis",
            "status": "error",
            "required": required,
            "error": str(exc)[:180],
        }


def clickhouse_check(required: bool = False) -> dict:
    try:
        import os
        import urllib.request

        host = os.getenv("CLICKHOUSE_HOST", "localhost")
        port = os.getenv("CLICKHOUSE_PORT", "8123")
        with urllib.request.urlopen(f"http://{host}:{port}/ping", timeout=1.5) as resp:
            ok = 200 <= resp.status < 300
        return {"name": "clickhouse", "status": "ok" if ok else "error", "required": required}
    except Exception as exc:
        return {
            "name": "clickhouse",
            "status": "error" if required else "degraded",
            "required": required,
            "error": str(exc)[:180],
        }


def readiness_response(service_name: str, response: Response, checks: Iterable[ReadyCheck]) -> dict:
    results = [check() for check in checks]
    ready = all(item["status"] == "ok" for item in results if item.get("required"))
    if not ready:
        response.status_code = 503
    return {"status": "ready" if ready else "not_ready", "service": service_name, "checks": results}
