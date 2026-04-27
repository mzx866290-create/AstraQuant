"""
分析服务 - FastAPI 入口
技术分析 / 多股对比 / 综合评分 / K线形态 / AI分析
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uuid
import time
import logging
import sys
import os

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
sys.path.insert(0, _SERVICE_DIR)
sys.path.insert(0, _PROJECT_ROOT)

# 本地运行：检测并启用 SQLite 模式
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

from api.v1 import technical, compare, scoring, patterns
from api.v1 import financial_analysis, valuation
from api.v1.admin_models import router as admin_models_router
from api.v1.admin_users import router as admin_users_router
from api.v1.admin_stats import router as admin_stats_router
from api.v1.admin_logs import router as admin_logs_router
from api.v1.ai_analysis import router as ai_analysis_router

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("分析服务启动中...")
    try:
        from backend.shared.database import init_db
        init_db()
        logger.info("数据库表初始化成功")
    except Exception as e:
        logger.warning(f"数据库初始化跳过: {e}")
    try:
        from backend.shared.cache import init_redis
        await init_redis()
    except Exception:
        logger.info("Redis不可用，分析服务将以无缓存模式运行")
    yield
    try:
        from backend.shared.cache import close_redis
        await close_redis()
    except Exception:
        pass
    logger.info("分析服务关闭中...")


app = FastAPI(
    title="StockPlatform - 分析服务",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5175", "http://localhost:5173",
        "http://localhost", "http://localhost:80",
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
# 分析相关
app.include_router(technical.router,  prefix="/api/v1/analysis/technical", tags=["技术分析"])
app.include_router(compare.router,    prefix="/api/v1/analysis/compare",   tags=["多股对比"])
app.include_router(scoring.router,    prefix="/api/v1/analysis/score",     tags=["综合评分"])
app.include_router(patterns.router,   prefix="/api/v1/analysis/patterns",  tags=["K线形态"])

# 财务分析 & 估值
app.include_router(financial_analysis.router, prefix="/api/v1/analysis/financial", tags=["财务分析"])
app.include_router(valuation.router,          prefix="/api/v1/analysis/valuation", tags=["估值分析"])

# AI 分析 (用户端)
app.include_router(ai_analysis_router, prefix="/api/v1/analysis", tags=["AI分析"])

# 管理员 API
app.include_router(admin_models_router, prefix="/api/v1/admin", tags=["管理员-模型管理"])
app.include_router(admin_users_router,  prefix="/api/v1/admin", tags=["管理员-用户管理"])
app.include_router(admin_stats_router,  prefix="/api/v1/admin", tags=["管理员-统计"])
app.include_router(admin_logs_router,   prefix="/api/v1/admin", tags=["管理员-日志"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "analysis-service", "version": "2.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8003, reload=False)
