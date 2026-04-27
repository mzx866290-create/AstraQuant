#!/usr/bin/env python3
"""
股票数据分析平台 API
简化版本，无需数据库
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="股票数据分析平台",
    description="简化版API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 模拟股票数据
MOCK_STOCKS = [
    {"symbol": "000001", "name": "平安银行", "price": 10.50, "change": 0.05},
    {"symbol": "000002", "name": "万科A", "price": 9.80, "change": -0.02},
    {"symbol": "600519", "name": "贵州茅台", "price": 1700.00, "change": 1.20},
    {"symbol": "000858", "name": "五粮液", "price": 145.50, "change": 0.80},
]

@app.get("/")
def root():
    return {"message": "股票数据分析平台 API"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/v1/stocks")
def get_stocks():
    return {"stocks": MOCK_STOCKS}

@app.get("/api/v1/stocks/{symbol}")
def get_stock_detail(symbol: str):
    for stock in MOCK_STOCKS:
        if stock["symbol"] == symbol:
            return stock
    return {"error": "股票代码不存在"}

if __name__ == "__main__":
    print("=" * 50)
    print("股票数据分析平台 API")
    print("=" * 50)
    print("地址: http://localhost:8080")
    print("文档: http://localhost:8080/docs")
    print("按 Ctrl+C 停止")
    print("=" * 50)
    print()
    uvicorn.run(app, host="0.0.0.0", port=8080)