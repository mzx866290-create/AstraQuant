"""
搜索API - 本地数据库搜索
"""
import os
import sys
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

router = APIRouter(tags=["搜索"])

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
sys.path.insert(0, _PROJECT_ROOT)


@router.get("")
async def search_stocks(
    q: str = Query(..., min_length=1, max_length=50, description="搜索关键词"),
    market: Optional[str] = Query(None, description="市场筛选: SH/SZ"),
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
):
    """搜索A股股票（本地数据库）"""
    from backend.shared.database import SessionLocal
    from backend.shared.models import Stock

    keyword = q.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="请输入搜索关键词")

    db = SessionLocal()
    try:
        query = db.query(Stock).filter(
            (Stock.symbol.like(f"%{keyword}%")) | (Stock.name.like(f"%{keyword}%"))
        )
        if market:
            query = query.filter(Stock.market == market)
        stocks = query.limit(limit).all()

        results = []
        for s in stocks:
            code = s.symbol[:6]
            results.append({
                "symbol": f"{code}.{s.market}",
                "name": s.name,
                "market": s.market,
                "pinyin": "",
            })

        return {"results": results, "total": len(results), "query": q}
    finally:
        db.close()
