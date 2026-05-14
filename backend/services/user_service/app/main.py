"""
用户服务 - FastAPI 入口 v2
认证 / 自选股管理 / 用户信息
"""
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uuid
import time
import logging
import sys
import os
from dotenv import load_dotenv

# 加载 .env 文件（本地开发时使用）
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _SERVICE_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from backend.shared.config import fastapi_docs_kwargs, is_production, validate_production_settings
from backend.shared.observability import database_check, install_metrics, readiness_response, redis_check

dotenv_path = os.path.join(_PROJECT_ROOT, ".env")
if not is_production() and os.path.exists(dotenv_path):
    load_dotenv(dotenv_path, override=True)

# 本地运行：检测并启用 SQLite 模式
if not is_production():
    _db_host = os.getenv("DB_HOST", "")
    if _db_host in (None, "", "postgres"):
        os.environ["DB_HOST"] = "localhost"
    if os.getenv("USE_SQLITE", "").lower() != "true" and _db_host in (None, "", "postgres", "localhost"):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            if s.connect_ex(("localhost", 5432)) != 0:
                os.environ["USE_SQLITE"] = "true"
            s.close()
        except Exception:
            os.environ["USE_SQLITE"] = "true"

validate_production_settings("user-service")

from backend.shared.database import init_db
from backend.shared.cache import init_redis, close_redis
from app.api.v1 import auth, watchlist_routes

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("用户服务启动中...")
    try:
        init_db()
        await init_redis()
        logger.info("数据库和缓存初始化成功")
    except Exception as e:
        logger.warning(f"数据库连接失败，服务将以离线模式运行: {e}")
    yield
    logger.info("用户服务关闭中...")
    try:
        await close_redis()
    except Exception:
        pass


app = FastAPI(
    title="StockPlatform - 用户服务",
    version="2.0.0",
    lifespan=lifespan,
    **fastapi_docs_kwargs(),
)

install_metrics(app, "user-service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5175", "http://localhost:5173",
        "http://localhost", "http://localhost:80",
        "https://yhang.cc.cd",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
app.include_router(auth.router,             prefix="/api/v1", tags=["认证"])
app.include_router(watchlist_routes.router,  prefix="/api/v1", tags=["自选股"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "user-service", "version": "2.0"}


@app.get("/ready")
async def ready_check(response: Response):
    return readiness_response(
        "user-service",
        response,
        checks=[database_check, lambda: redis_check(required=False)],
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8002, reload=False)
