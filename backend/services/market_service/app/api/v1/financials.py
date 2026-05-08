"""
财报查询 API — 个股财务报表核心指标
"""
from fastapi import APIRouter, Query, HTTPException
from datetime import datetime
from typing import Optional

router = APIRouter(tags=["财报"])


def _data_quality(source: str, updated_at: Optional[str] = None, freshness: str = "reported",
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

    if not isinstance(limit, int):
        limit = 8

    db = SessionLocal()
    try:
        live_loaded = False
        items = (
            db.query(FinancialReport)
            .filter(FinancialReport.stock_symbol == symbol[:6])
            .order_by(FinancialReport.report_date.desc())
            .limit(limit)
            .all()
        )
        if not items:
            try:
                from backend.services.data_crawler.sources import AKShareSource
                from backend.services.data_crawler.pipeline.financial_etl import FinancialReportETL

                source = AKShareSource()
                balance = await source.fetch_balance_sheet(symbol[:6])
                profit = await source.fetch_profit_sheet(symbol[:6])
                cashflow = await source.fetch_cash_flow_sheet(symbol[:6])
                await FinancialReportETL().save(db, symbol[:6], balance, profit, cashflow, source.name)
                live_loaded = True
                items = (
                    db.query(FinancialReport)
                    .filter(FinancialReport.stock_symbol == symbol[:6])
                    .order_by(FinancialReport.report_date.desc())
                    .limit(limit)
                    .all()
                )
            except Exception:
                items = []

        warnings = []
        if not items:
            warnings.append("no financial reports available")
        source_names = sorted({r.source for r in items if r.source}) if items else []
        quality_source = ",".join(source_names) if source_names else ("akshare" if live_loaded else "database")
        latest_report_date = items[0].report_date.isoformat() if items and items[0].report_date else None
        updated_at = datetime.now().isoformat()
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
            "updated_at": updated_at,
            "data_quality": _data_quality(
                source=quality_source,
                updated_at=latest_report_date or updated_at,
                freshness="reported" if items else "empty",
                confidence=0.85 if items else 0.2,
                is_fallback=False,
                warnings=warnings,
            ),
        }
    finally:
        db.close()
