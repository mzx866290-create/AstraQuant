"""
股票列表 API
"""
import os
import sys
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

router = APIRouter(tags=["股票列表"])

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
sys.path.insert(0, _PROJECT_ROOT)


@router.get("")
async def get_stocks(
    market: Optional[str] = Query(None, description="市场筛选: SH/SZ"),
    limit: int = Query(50, ge=1, le=500, description="返回条数"),
):
    """获取A股股票列表"""
    try:
        from backend.shared.database import SessionLocal
        from backend.shared.models import Stock

        db = SessionLocal()
        try:
            query = db.query(Stock).filter(Stock.is_active == True)
            if market:
                query = query.filter(Stock.market == market)
            stocks = query.limit(limit).all()
            return {
                "stocks": [
                    {
                        "id": s.id,
                        "symbol": s.symbol,
                        "name": s.name,
                        "market": s.market,
                        "sector": s.sector,
                    }
                    for s in stocks
                ],
                "total": len(stocks),
            }
        finally:
            db.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取股票列表失败: {str(e)}")


@router.get("/{symbol}")
async def get_stock(symbol: str):
    """获取A股股票基本信息"""
    if not symbol or len(symbol) < 6:
        raise HTTPException(status_code=400, detail="无效的股票代码")

    code = symbol[:6] if len(symbol) >= 6 else symbol
    market = "SH" if code.startswith(("6", "9")) else "SZ"

    try:
        from backend.shared.database import SessionLocal
        from backend.shared.models import Stock

        db = SessionLocal()
        try:
            stock = db.query(Stock).filter(Stock.symbol.like(f"{code}%")).first()
            if stock:
                return {
                    "id": stock.id,
                    "symbol": stock.symbol,
                    "name": stock.name,
                    "market": stock.market,
                    "sector": stock.sector,
                    "list_date": stock.list_date.isoformat() if stock.list_date else None,
                }
        finally:
            db.close()
    except Exception:
        pass

    return {
        "symbol": f"{code}.{market}",
        "code": code,
        "market": market,
        "name": "",
        "sector": "",
        "list_date": None,
    }
