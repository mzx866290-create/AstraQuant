"""
Sector APIs backed by the local stock profile database.
"""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func

router = APIRouter(tags=["板块"])


def _api_symbol(symbol: str, market: str) -> str:
    code = symbol[:6] if symbol else ""
    inferred_market = "SH" if code.startswith(("6", "9")) else "SZ"
    return f"{code}.{market or inferred_market}"


@router.get("")
async def get_sectors(
    limit: int = Query(80, ge=1, le=300, description="返回板块数量"),
):
    """Return industry sectors inferred from active stock profiles."""
    try:
        from backend.shared.database import SessionLocal
        from backend.shared.models import Stock

        db = SessionLocal()
        try:
            rows = (
                db.query(Stock.sector, func.count(Stock.id).label("stock_count"))
                .filter(Stock.is_active == True)
                .filter(Stock.sector.isnot(None))
                .filter(Stock.sector != "")
                .group_by(Stock.sector)
                .order_by(func.count(Stock.id).desc(), Stock.sector.asc())
                .limit(limit)
                .all()
            )
            sectors = [
                {
                    "name": sector,
                    "stock_count": int(stock_count or 0),
                    "change_pct": None,
                    "turnover": None,
                    "source": "stock_profile_database",
                }
                for sector, stock_count in rows
            ]
            return {
                "sectors": sectors,
                "count": len(sectors),
                "source": "stock_profile_database",
            }
        finally:
            db.close()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取板块列表失败: {exc}")


@router.get("/{sector_name}/stocks")
async def get_sector_stocks(
    sector_name: str,
    limit: int = Query(100, ge=1, le=500, description="返回股票数量"),
    offset: int = Query(0, ge=0, description="分页偏移量"),
):
    """Return stocks in an industry sector."""
    try:
        from backend.shared.database import SessionLocal
        from backend.shared.models import Stock

        db = SessionLocal()
        try:
            query = (
                db.query(Stock)
                .filter(Stock.is_active == True)
                .filter(Stock.sector == sector_name)
            )
            total = query.count()
            stocks = (
                query.order_by(Stock.symbol.asc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return {
                "sector": sector_name,
                "stocks": [
                    {
                        "id": stock.id,
                        "symbol": _api_symbol(stock.symbol, stock.market),
                        "name": stock.name,
                        "market": stock.market,
                        "sector": stock.sector,
                    }
                    for stock in stocks
                ],
                "total": total,
                "count": len(stocks),
                "limit": limit,
                "offset": offset,
                "source": "stock_profile_database",
            }
        finally:
            db.close()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取板块成分股失败: {exc}")
