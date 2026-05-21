"""
行情服务 - FastAPI 入口 v2
A股行情 / K线 / 搜索 / 板块
"""
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import uuid
import time
import logging
import sys
import os
from dotenv import load_dotenv

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
sys.path.insert(0, _SERVICE_DIR)   # 让 app 包可导入
sys.path.insert(0, _PROJECT_ROOT)  # 让 backend 包可导入

from backend.shared.config import fastapi_docs_kwargs, is_production, validate_production_settings
from backend.shared.observability import (
    clickhouse_check,
    database_check,
    install_metrics,
    readiness_response,
    redis_check,
)

dotenv_path = os.path.join(_PROJECT_ROOT, ".env")
if not is_production() and os.path.exists(dotenv_path):
    load_dotenv(dotenv_path, override=True)

from backend.shared.auth import get_current_user, get_token_from_auth

# 本地运行：检测并启用 SQLite 模式
if not is_production():
    _db_host = os.getenv("DB_HOST", "")
    if _db_host in (None, ""):
        os.environ["DB_HOST"] = "localhost"
        _db_host = "localhost"
    if os.getenv("USE_SQLITE", "").lower() != "true" and _db_host in ("localhost", "127.0.0.1"):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            if s.connect_ex((_db_host, 5432)) != 0:
                os.environ["USE_SQLITE"] = "true"
            s.close()
        except Exception:
            os.environ["USE_SQLITE"] = "true"

validate_production_settings("market-service")

from app.api.v1 import quotes, kline, search, sectors, alerts, index_market, stocks
from app.api.v1 import announcements, financials, news_api, crawl

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("行情服务启动中...")
    try:
        from backend.shared.database import init_db
        init_db()
    except Exception as e:
        logger.warning(f"数据库初始化跳过: {e}")
    try:
        from backend.shared.cache import init_redis
        await init_redis()
    except Exception:
        logger.info("Redis不可用，行情服务将以无缓存模式运行")
    try:
        from backend.services.market_service.app.tasks.alert_scheduler import alert_scheduler
        alert_scheduler.start()
    except Exception as e:
        logger.warning(f"预警自动检查任务启动跳过: {e}")
    yield
    try:
        from backend.services.market_service.app.tasks.alert_scheduler import alert_scheduler
        await alert_scheduler.stop()
    except Exception:
        pass
    try:
        from backend.shared.cache import close_redis
        await close_redis()
    except Exception:
        pass
    logger.info("行情服务关闭中...")


app = FastAPI(
    title="StockPlatform - 行情服务 (A股)",
    version="2.0.0",
    lifespan=lifespan,
    **fastapi_docs_kwargs(),
)

install_metrics(app, "market-service")

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "https://yhang.cc.cd,http://localhost:5175,http://localhost:5173",
    ).split(",")
    if origin.strip()
]

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _credentials_from_request(request: Request) -> HTTPAuthorizationCredentials | None:
    token = get_token_from_auth(auth_header=request.headers.get("authorization"))
    if not token:
        return None
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


PUBLIC_READ_PREFIXES = (
    "/api/v1/stocks",
    "/api/v1/quotes",
    "/api/v1/kline",
    "/api/v1/search",
    "/api/v1/sectors",
    "/api/v1/indices",
    "/api/v1/announcements",
    "/api/v1/financials",
    "/api/v1/news",
)


def _is_public_read_path(request: Request) -> bool:
    path = request.url.path
    if request.method != "GET":
        return False
    if path.startswith(PUBLIC_READ_PREFIXES):
        return True
    return path.startswith("/api/v1/crawl/") and path.endswith("/status")


@app.middleware("http")
async def api_authentication(request: Request, call_next):
    if request.method == "OPTIONS" or not request.url.path.startswith("/api/v1") or _is_public_read_path(request):
        return await call_next(request)
    try:
        request.state.current_user = await get_current_user(_credentials_from_request(request))
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    return await call_next(request)


@app.middleware("http")
async def request_tracking(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{elapsed}ms"
    logger.info(f"[{request_id}] {request.method} {request.url.path} -> {response.status_code} ({elapsed}ms)")
    return response


# ─── 注册路由 v1 ───
app.include_router(stocks.router,        prefix="/api/v1/stocks",        tags=["股票列表"])
app.include_router(quotes.router,        prefix="/api/v1/quotes",        tags=["行情"])
app.include_router(kline.router,         prefix="/api/v1/kline",         tags=["K线"])
app.include_router(search.router,        prefix="/api/v1/search",        tags=["搜索"])
app.include_router(sectors.router,       prefix="/api/v1/sectors",       tags=["板块"])
app.include_router(alerts.router,        prefix="/api/v1",               tags=["预警"])
app.include_router(index_market.router,  prefix="/api/v1/indices",       tags=["大盘指数"])
app.include_router(announcements.router, prefix="/api/v1/announcements", tags=["公告"])
app.include_router(financials.router,    prefix="/api/v1/financials",    tags=["财报"])
app.include_router(news_api.router,      prefix="/api/v1/news",          tags=["新闻"])
app.include_router(crawl.router,         prefix="/api/v1/crawl",         tags=["数据采集"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "market-service", "version": "2.0"}


@app.get("/ready")
async def ready_check(response: Response):
    return readiness_response(
        "market-service",
        response,
        checks=[
            database_check,
            lambda: redis_check(required=False),
            lambda: clickhouse_check(required=False),
        ],
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=os.getenv("BIND_HOST", "0.0.0.0"), port=8001, reload=False)
