"""
新闻查询 API — 个股实时新闻流 + 财联社电报
"""
from fastapi import APIRouter, Query, HTTPException
from datetime import datetime
from typing import Optional

router = APIRouter(tags=["新闻"])


@router.get("/{symbol}")
async def get_stock_news(
    symbol: str,
    limit: int = Query(20, ge=5, le=100),
    sentiment: Optional[str] = Query(None, description="筛选情感: 正面/中性/负面"),
    min_impact: Optional[str] = Query(None, description="最低影响力: 高/中/低"),
):
    """
    获取个股实时新闻流，含情感标签和影响力评分
    """
    from backend.shared.database import SessionLocal
    from backend.shared.models import StockNews

    db = SessionLocal()
    try:
        q = db.query(StockNews).filter(
            StockNews.stock_symbol == symbol[:6]
        )
        if sentiment:
            q = q.filter(StockNews.sentiment == sentiment)
        if min_impact:
            if min_impact == "高":
                q = q.filter(StockNews.impact_level == "高")
            elif min_impact == "中":
                q = q.filter(StockNews.impact_level.in_(["高", "中"]))

        q = q.order_by(StockNews.publish_time.desc()).limit(limit)
        items = q.all()

        pos = sum(1 for n in items if n.sentiment == "正面")
        neg = sum(1 for n in items if n.sentiment == "负面")
        neu = sum(1 for n in items if n.sentiment == "中性")

        return {
            "symbol": symbol[:6],
            "count": len(items),
            "sentiment_summary": {
                "positive": pos, "negative": neg, "neutral": neu,
                "dominant": "正面" if pos >= neg and pos >= neu
                           else "负面" if neg >= pos else "中性",
            },
            "news": [
                {
                    "id": n.id,
                    "title": n.title,
                    "summary": n.summary[:300] if n.summary else "",
                    "source": n.source,
                    "url": n.url,
                    "publish_time": n.publish_time.isoformat() if n.publish_time else "",
                    "sentiment": n.sentiment,
                    "sentiment_score": n.sentiment_score,
                    "impact_level": n.impact_level,
                    "event_category": n.event_category,
                    "related_sector": n.related_sector,
                    "keywords": n.keywords,
                    "source_authority": _source_authority(n.source),
                }
                for n in items
            ],
            "updated_at": datetime.now().isoformat(),
        }
    finally:
        db.close()


@router.get("/telegraph/latest")
async def get_telegraph(
    limit: int = Query(30, ge=5, le=100),
):
    """
    获取财联社实时电报（全市场级别快讯）
    """
    from backend.shared.database import SessionLocal
    from backend.shared.models import StockNews

    db = SessionLocal()
    try:
        items = (
            db.query(StockNews)
            .filter(StockNews.source == "财联社")
            .order_by(StockNews.publish_time.desc())
            .limit(limit)
            .all()
        )

        return {
            "count": len(items),
            "telegraphs": [
                {
                    "id": n.id,
                    "title": n.title,
                    "summary": n.summary,
                    "publish_time": n.publish_time.isoformat() if n.publish_time else "",
                    "keywords": n.keywords,
                }
                for n in items
            ],
            "updated_at": datetime.now().isoformat(),
        }
    finally:
        db.close()


def _source_authority(source: str) -> str:
    authority = {
        "证监会": "权威", "上交所": "权威", "深交所": "权威",
        "央行": "权威", "国务院": "权威",
        "财联社": "可靠", "证券时报": "可靠", "中国证券报": "可靠",
        "东方财富": "一般", "新浪财经": "一般", "同花顺": "一般",
    }
    return authority.get(source, "未知")
