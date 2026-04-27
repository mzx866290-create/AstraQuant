"""
公告查询 API — 个股公告列表
"""
from fastapi import APIRouter, Query, HTTPException
from datetime import datetime
from typing import Optional

router = APIRouter(tags=["公告"])


@router.get("/{symbol}")
async def get_announcements(
    symbol: str,
    limit: int = Query(20, ge=5, le=100),
    category: Optional[str] = Query(None, description="筛选: 定期报告/临时公告/业绩预告/分红送转"),
):
    """
    获取个股公告列表

    - **symbol**: 600519
    - **category**: 可选筛选 (定期报告/临时公告/业绩预告/分红送转/股东变动/重大事项)
    """
    from backend.shared.database import SessionLocal
    from backend.shared.models import CompanyAnnouncement

    db = SessionLocal()
    try:
        q = db.query(CompanyAnnouncement).filter(
            CompanyAnnouncement.stock_symbol == symbol[:6]
        )
        if category:
            q = q.filter(CompanyAnnouncement.category == category)
        q = q.order_by(CompanyAnnouncement.announce_date.desc()).limit(limit)
        items = q.all()

        return {
            "symbol": symbol[:6],
            "count": len(items),
            "announcements": [
                {
                    "id": a.id,
                    "title": a.title,
                    "summary": a.summary[:200] if a.summary else "",
                    "announce_date": a.announce_date.isoformat() if a.announce_date else "",
                    "category": a.category or "临时公告",
                    "source": a.source,
                    "content_url": a.content_url,
                }
                for a in items
            ],
            "updated_at": datetime.now().isoformat(),
        }
    finally:
        db.close()
