"""
财报查询 API — 个股财务报表核心指标
"""
from fastapi import APIRouter, Query, HTTPException
from datetime import datetime
from typing import Optional

router = APIRouter(tags=["财报"])


@router.get("/{symbol}")
async def get_financials(
    symbol: str,
    limit: int = Query(8, ge=1, le=20, description="返回报告期数"),
):
    """
    获取个股财报核心指标

    - **symbol**: 600519
    - 返回: 最近N期报告的核心财务指标
    """
    from backend.shared.database import SessionLocal
    from backend.shared.models import FinancialReport

    db = SessionLocal()
    try:
        items = (
            db.query(FinancialReport)
            .filter(FinancialReport.stock_symbol == symbol[:6])
            .order_by(FinancialReport.report_date.desc())
            .limit(limit)
            .all()
        )

        return {
            "symbol": symbol[:6],
            "count": len(items),
            "reports": [
                {
                    "report_date": r.report_date.isoformat() if r.report_date else "",
                    "report_type": r.report_type,
                    "revenue": r.revenue,
                    "revenue_yoy": r.revenue_yoy,
                    "net_profit": r.net_profit,
                    "net_profit_yoy": r.net_profit_yoy,
                    "gross_margin": r.gross_margin,
                    "net_margin": r.net_margin,
                    "eps": r.eps,
                    "bvps": r.bvps,
                    "roe": r.roe,
                    "roa": r.roa,
                    "total_assets": r.total_assets,
                    "total_liabilities": r.total_liabilities,
                    "total_equity": r.total_equity,
                    "operating_cf": r.operating_cf,
                    "investing_cf": r.investing_cf,
                    "financing_cf": r.financing_cf,
                    "pe_ttm": r.pe_ttm,
                    "pb": r.pb,
                    "source": r.source,
                }
                for r in items
            ],
            "updated_at": datetime.now().isoformat(),
        }
    finally:
        db.close()
