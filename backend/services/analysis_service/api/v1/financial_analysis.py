"""
专业财务分析 API — 杜邦分析 + F-Score + Z-Score + 财务健康度
"""
from fastapi import APIRouter, Query, HTTPException
from datetime import datetime
import sys
import os

_SERVICE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.services.analysis_service.engine.financial_engine import FinancialAnalysisEngine

router = APIRouter(tags=["财务分析"])
fin_engine = FinancialAnalysisEngine()


@router.get("/{symbol}")
async def get_financial_analysis(symbol: str):
    """
    完整财务分析: 杜邦分解 + Piotroski F-Score + Altman Z-Score

    - **symbol**: 600519
    - 返回: 杜邦分解、F-Score、Z-Score、核心指标汇总
    """
    reports = _fetch_reports(symbol)

    if not reports:
        return {
            "symbol": symbol[:6],
            "status": "no_data",
            "message": "暂无财报数据，请先运行数据采集",
            "updated_at": datetime.now().isoformat(),
        }

    dupont = fin_engine.dupont_from_reports(reports)
    f_score = fin_engine.piotroski_f_score(reports[:2]) if len(reports) >= 2 else {}
    z_score = fin_engine.altman_z_score(reports[0]) if reports else {}
    summary = fin_engine.financial_health_summary(reports)

    return {
        "symbol": symbol[:6],
        "latest_report_date": str(reports[0].get("report_date", "")),
        "latest_report_type": reports[0].get("report_type", ""),
        "dupont": dupont,
        "f_score": f_score,
        "z_score": z_score,
        "summary": summary,
        "updated_at": datetime.now().isoformat(),
    }


@router.get("/{symbol}/dupont")
async def get_dupont(symbol: str):
    """杜邦分析 (ROE拆解)"""
    reports = _fetch_reports(symbol)
    dupont = fin_engine.dupont_from_reports(reports)
    return {"symbol": symbol[:6], "dupont": dupont,
            "updated_at": datetime.now().isoformat()}


@router.get("/{symbol}/fscore")
async def get_f_score(symbol: str):
    """Piotroski F-Score (基本面质量 0-9分)"""
    reports = _fetch_reports(symbol)
    if len(reports) < 2:
        return {"symbol": symbol[:6], "error": "需要至少两期财报",
                "updated_at": datetime.now().isoformat()}
    f_score = fin_engine.piotroski_f_score(reports[:2])
    return {"symbol": symbol[:6], "f_score": f_score,
            "updated_at": datetime.now().isoformat()}


def _fetch_reports(symbol: str) -> list[dict]:
    """从DB获取财报"""
    from backend.shared.database import SessionLocal
    from backend.shared.models import FinancialReport

    db = SessionLocal()
    try:
        items = (
            db.query(FinancialReport)
            .filter(FinancialReport.stock_symbol == symbol[:6])
            .order_by(FinancialReport.report_date.desc())
            .limit(8)
            .all()
        )
        return [_report_to_dict(r) for r in items]
    finally:
        db.close()


def _report_to_dict(r) -> dict:
    return {
        "report_date": r.report_date.isoformat() if r.report_date else "",
        "report_type": r.report_type,
        "revenue": r.revenue, "revenue_yoy": r.revenue_yoy,
        "net_profit": r.net_profit, "net_profit_yoy": r.net_profit_yoy,
        "gross_margin": r.gross_margin, "net_margin": r.net_margin,
        "eps": r.eps, "bvps": r.bvps,
        "roe": r.roe, "roa": r.roa,
        "total_assets": r.total_assets, "total_liabilities": r.total_liabilities,
        "total_equity": r.total_equity,
        "current_assets": r.current_assets, "current_liabilities": r.current_liabilities,
        "operating_cf": r.operating_cf, "investing_cf": r.investing_cf,
        "financing_cf": r.financing_cf,
        "pe_ttm": r.pe_ttm, "pb": r.pb,
        "source": r.source,
    }
