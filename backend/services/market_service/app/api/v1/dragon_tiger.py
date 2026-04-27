"""
龙虎榜API - A股龙虎榜数据
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from datetime import date

router = APIRouter(tags=["龙虎榜"])


@router.get("")
async def get_dragon_tiger(
    trade_date: Optional[date] = Query(None, description="交易日期"),
    limit: int = Query(50, ge=1, le=200),
):
    """获取龙虎榜数据"""
    raise HTTPException(status_code=501, detail="龙虎榜服务待接入")


@router.get("/{symbol}")
async def get_stock_dragon_tiger(symbol: str, days: int = 30):
    """获取个股龙虎榜历史"""
    raise HTTPException(status_code=501, detail="龙虎榜服务待接入")
