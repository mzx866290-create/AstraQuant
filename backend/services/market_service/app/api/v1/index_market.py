"""
大盘指数 API - A股主要指数行情
上证/深证/创业板/科创50/沪深300
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["大盘指数"])


# A股主要指数代码
INDEX_MAP = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000688.SH": "科创50",
    "000300.SH": "沪深300",
    "000016.SH": "上证50",
    "000905.SH": "中证500",
}


@router.get("")
async def get_index_list():
    """获取A股主要指数列表"""
    return {
        "indices": [
            {"symbol": k, "name": v} for k, v in INDEX_MAP.items()
        ]
    }


@router.get("/{symbol}")
async def get_index_detail(symbol: str):
    """获取单个指数详情（含最新行情）"""
    if symbol not in INDEX_MAP:
        raise HTTPException(status_code=404, detail="指数不存在")

    raise HTTPException(status_code=501, detail="指数行情服务待接入真实数据")


@router.get("/{symbol}/kline")
async def get_index_kline(symbol: str, limit: int = 120):
    """获取指数K线数据"""
    if symbol not in INDEX_MAP:
        raise HTTPException(status_code=404, detail="指数不存在")

    raise HTTPException(status_code=501, detail="指数K线服务待接入")


@router.get("/summary/market-overview")
async def get_market_overview():
    """
    市场概览：涨跌家数、涨停跌停、成交额
    """
    raise HTTPException(status_code=501, detail="市场概览服务待接入真实数据")
