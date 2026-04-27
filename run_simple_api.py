#!/usr/bin/env python3
"""
简化版股票数据平台 - 直接运行
无需数据库和Docker
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="股票数据分析平台",
    description="简化版API (无需数据库)",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ 模拟数据 ============
MOCK_STOCKS = [
    {"symbol": "000001", "name": "平安银行", "price": 10.50, "change_pct": 0.05, "volume": 12345678},
    {"symbol": "000002", "name": "万科A", "price": 9.80, "change_pct": -0.02, "volume": 9876543},
    {"symbol": "600519", "name": "贵州茅台", "price": 1700.00, "change_pct": 1.20, "volume": 2345678},
    {"symbol": "000858", "name": "五粮液", "price": 145.50, "change_pct": 0.80, "volume": 3456789},
    {"symbol": "600036", "name": "招商银行", "price": 35.60, "change_pct": -0.30, "volume": 5678901},
    {"symbol": "601318", "name": "中国平安", "price": 45.20, "change_pct": 0.15, "volume": 6789012},
    {"symbol": "300750", "name": "宁德时代", "price": 198.00, "change_pct": 2.50, "volume": 4567890},
    {"symbol": "002415", "name": "海康威视", "price": 32.80, "change_pct": -0.50, "volume": 3456789},
]

MOCK_MARKET_INDEX = {
    "shanghai": {"name": "上证指数", "value": 3350.25, "change": 0.35},
    "shenzhen": {"name": "深证成指", "value": 11200.80, "change": 0.68},
    "chi_next": {"name": "创业板指", "value": 2280.50, "change": 1.20},
}

# ============ API 端点 ============

@app.get("/")
def root():
    return {"message": "股票数据分析平台 API", "version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "simplified-api"}

@app.get("/api/v1/stocks")
def get_stocks():
    """获取所有股票列表"""
    return {"stocks": MOCK_STOCKS}

@app.get("/api/v1/stocks/{symbol}")
def get_stock_detail(symbol: str):
    """获取单只股票详情"""
    for stock in MOCK_STOCKS:
        if stock["symbol"] == symbol:
            return stock
    return {"error": "股票代码不存在", "symbol": symbol}

@app.get("/api/v1/market/index")
def get_market_index():
    """获取大盘指数"""
    return MOCK_MARKET_INDEX

@app.get("/api/v1/market/hot")
def get_hot_stocks():
    """获取热门股票"""
    sorted_stocks = sorted(MOCK_STOCKS, key=lambda x: abs(x["change_pct"]), reverse=True)
    return {"hot_stocks": sorted_stocks[:5]}

if __name__ == "__main__":
    print()
    print("=" * 50)
    print("  股票数据分析平台 - 简化版API")
    print("=" * 50)
    print()
    print("API地址: http://localhost:8000")
    print("API文档: http://localhost:8000/docs")
    print("健康检查: http://localhost:8000/health")
    print("股票列表: http://localhost:8000/api/v1/stocks")
    print()
    print("按 Ctrl+C 停止服务")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)

