"""
Financial report query APIs.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter(tags=["财报"])


def _data_quality(
    source: str,
    updated_at: Optional[str] = None,
    freshness: str = "reported",
    confidence: float = 0.85,
    is_fallback: bool = False,
    warnings: Optional[list[str]] = None,
    status: Optional[str] = None,
) -> dict:
    quality_warnings = warnings or []
    return {
        "source": source,
        "status": status or ("degraded" if quality_warnings else "ok"),
        "updated_at": updated_at or datetime.now().isoformat(),
        "freshness": freshness,
        "confidence": confidence,
        "is_fallback": is_fallback,
        "warnings": quality_warnings,
    }


@router.get("/{symbol}")
async def get_financials(
    symbol: str,
    limit: int = Query(8, ge=1, le=20, description="返回报告期数"),
    refresh: bool = Query(False, description="本地无数据时是否尝试实时抓取财报"),
):
    """Return financial reports from the local database, optionally refreshing from AKShare."""
    from backend.shared.database import SessionLocal
    from backend.shared.models import FinancialReport

    if not isinstance(limit, int):
        limit = 8

    db = SessionLocal()
    try:
        live_loaded = False
        code = symbol[:6]
        items = (
            db.query(FinancialReport)
            .filter(FinancialReport.stock_symbol == code)
            .order_by(FinancialReport.report_date.desc())
            .limit(limit)
            .all()
        )

        # Public page loads should not block on slow third-party financial crawlers.
        # Operators can still request a live refresh explicitly when needed.
        if not items and refresh:
            try:
                from backend.services.data_crawler.pipeline.financial_etl import FinancialReportETL
                from backend.services.data_crawler.sources import AKShareSource

                source = AKShareSource()
                balance = await source.fetch_balance_sheet(code)
                profit = await source.fetch_profit_sheet(code)
                cashflow = await source.fetch_cash_flow_sheet(code)
                await FinancialReportETL().save(db, code, balance, profit, cashflow, source.name)
                live_loaded = True
                items = (
                    db.query(FinancialReport)
                    .filter(FinancialReport.stock_symbol == code)
                    .order_by(FinancialReport.report_date.desc())
                    .limit(limit)
                    .all()
                )
            except Exception:
                items = []

        warnings = []
        if not items:
            warnings.append("no financial reports available")
        source_names = sorted({report.source for report in items if report.source}) if items else []
        quality_source = ",".join(source_names) if source_names else ("akshare" if live_loaded else "database")
        latest_report_date = items[0].report_date.isoformat() if items and items[0].report_date else None
        updated_at = datetime.now().isoformat()
        return {
            "symbol": code,
            "count": len(items),
            "reports": [
                {
                    "report_date": report.report_date.isoformat() if report.report_date else "",
                    "report_type": report.report_type,
                    "revenue": report.revenue,
                    "revenue_yoy": report.revenue_yoy,
                    "net_profit": report.net_profit,
                    "net_profit_yoy": report.net_profit_yoy,
                    "gross_margin": report.gross_margin,
                    "net_margin": report.net_margin,
                    "eps": report.eps,
                    "bvps": report.bvps,
                    "roe": report.roe,
                    "roa": report.roa,
                    "total_assets": report.total_assets,
                    "total_liabilities": report.total_liabilities,
                    "total_equity": report.total_equity,
                    "operating_cf": report.operating_cf,
                    "investing_cf": report.investing_cf,
                    "financing_cf": report.financing_cf,
                    "pe_ttm": report.pe_ttm,
                    "pb": report.pb,
                    "source": report.source,
                }
                for report in items
            ],
            "updated_at": updated_at,
            "data_quality": _data_quality(
                source=quality_source,
                updated_at=latest_report_date or updated_at,
                freshness="reported" if items else "empty",
                confidence=0.85 if items else 0.2,
                is_fallback=live_loaded,
                warnings=warnings,
                status="ok" if items else "empty",
            ),
        }
    finally:
        db.close()
