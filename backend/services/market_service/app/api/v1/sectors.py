"""
板块API - A股行业板块 + 概念板块
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["板块"])


@router.get("")
async def get_sectors():
    """获取行业板块列表及涨跌幅排名"""
    raise HTTPException(status_code=501, detail="板块服务待接入")


@router.get("/{sector_name}/stocks")
async def get_sector_stocks(sector_name: str):
    """获取板块内成份股"""
    raise HTTPException(status_code=501, detail="板块服务待接入")
