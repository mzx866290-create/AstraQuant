"""
公告查询 API — 个股公告列表
"""
from fastapi import APIRouter, Query, HTTPException
from datetime import datetime
from typing import Optional

router = APIRouter(tags=["公告"])


def _data_quality(source: str, updated_at: Optional[str] = None, freshness: str = "published",
                  confidence: float = 0.85, is_fallback: bool = False,
                  warnings: Optional[list[str]] = None) -> dict:
    return {
        "source": source,
        "updated_at": updated_at or datetime.now().isoformat(),
        "freshness": freshness,
        "confidence": confidence,
        "is_fallback": is_fallback,
        "warnings": warnings or [],
    }


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

    if not isinstance(limit, int):
        limit = 20
    if not isinstance(category, str):
        category = None

    db = SessionLocal()
    try:
        live_loaded = False
        q = db.query(CompanyAnnouncement).filter(
            CompanyAnnouncement.stock_symbol == symbol[:6]
        )
        if category:
            q = q.filter(CompanyAnnouncement.category == category)
        q = q.order_by(CompanyAnnouncement.announce_date.desc()).limit(limit)
        items = q.all()
        if not items:
            try:
                from backend.services.data_crawler.sources import AKShareSource
                from backend.services.data_crawler.pipeline.financial_etl import AnnouncementETL

                source = AKShareSource()
                notices = await source.fetch_stock_notices(symbol[:6], limit=limit)
                await AnnouncementETL().save(db, symbol[:6], notices, "CNINFO")
                live_loaded = True
                q = db.query(CompanyAnnouncement).filter(
                    CompanyAnnouncement.stock_symbol == symbol[:6]
                )
                if category:
                    q = q.filter(CompanyAnnouncement.category == category)
                items = q.order_by(CompanyAnnouncement.announce_date.desc()).limit(limit).all()
            except Exception:
                items = []

        warnings = []
        if not items:
            warnings.append("no announcements available")
        source_names = sorted({a.source for a in items if a.source}) if items else []
        quality_source = ",".join(source_names) if source_names else ("CNINFO" if live_loaded else "database")
        latest_announce_date = items[0].announce_date.isoformat() if items and items[0].announce_date else None
        updated_at = datetime.now().isoformat()
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
            "updated_at": updated_at,
            "data_quality": _data_quality(
                source=quality_source,
                updated_at=latest_announce_date or updated_at,
                freshness="published" if items else "empty",
                confidence=0.85 if items else 0.2,
                is_fallback=False,
                warnings=warnings,
            ),
        }
    finally:
        db.close()
