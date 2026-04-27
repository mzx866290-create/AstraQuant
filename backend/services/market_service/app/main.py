"""
行情服务 - FastAPI 入口 v2
A股行情 / K线 / 搜索 / 板块 / 龙虎榜
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
sys.path.insert(0, _SERVICE_DIR)   # 让 app 包可导入
sys.path.insert(0, _PROJECT_ROOT)  # 让 backend 包可导入

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

from app.api.v1 import quotes, kline, search, sectors, dragon_tiger, alerts, index_market, stocks
from app.api.v1 import announcements, financials, news_api

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
    yield
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
    docs_url="/api/v1/docs",
)

# CORS
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
app.include_router(stocks.router,        prefix="/api/v1/stocks",        tags=["股票列表"])
app.include_router(quotes.router,        prefix="/api/v1/quotes",        tags=["行情"])
app.include_router(kline.router,         prefix="/api/v1/kline",         tags=["K线"])
app.include_router(search.router,        prefix="/api/v1/search",        tags=["搜索"])
app.include_router(sectors.router,       prefix="/api/v1/sectors",       tags=["板块"])
app.include_router(dragon_tiger.router,  prefix="/api/v1/dragon-tiger",  tags=["龙虎榜"])
app.include_router(alerts.router,        prefix="/api/v1/alerts",        tags=["预警"])
app.include_router(index_market.router,  prefix="/api/v1/indices",       tags=["大盘指数"])
app.include_router(announcements.router, prefix="/api/v1/announcements", tags=["公告"])
app.include_router(financials.router,    prefix="/api/v1/financials",    tags=["财报"])
app.include_router(news_api.router,      prefix="/api/v1/news",          tags=["新闻"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "market-service", "version": "2.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8001, reload=False)
