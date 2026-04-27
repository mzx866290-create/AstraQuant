"""
估值分析 API — PE/PB Band + Z-Score + 估值分位
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

router = APIRouter(tags=["估值分析"])
fin_engine = FinancialAnalysisEngine()


@router.get("/{symbol}")
async def get_valuation(symbol: str):
    """
    PE/PB Band 估值分析

    - **symbol**: 600519
    - 返回: PE/PB 历史分位、当前估值位置、Z-Score
    """
    historical_pes, current_pe = _fetch_pe_history(symbol)
    historical_pbs, current_pb = _fetch_pb_history(symbol)
    band = fin_engine.pe_pb_band(historical_pes, historical_pbs, current_pe, current_pb)

    reports = _fetch_reports(symbol)
    z_score = fin_engine.altman_z_score(reports[0]) if reports else {}

    return {
        "symbol": symbol[:6],
        "current_pe": current_pe,
        "current_pb": current_pb,
        "pe_band": band.get("pe_band", {}),
        "pb_band": band.get("pb_band", {}),
        "z_score": z_score,
        "updated_at": datetime.now().isoformat(),
    }


@router.get("/{symbol}/pe-band")
async def get_pe_band(symbol: str):
    """PE Band 单独查询"""
    historical_pes, current_pe = _fetch_pe_history(symbol)
    if not historical_pes:
        return {"symbol": symbol[:6], "error": "PE历史数据不足"}
    band = fin_engine.pe_pb_band(historical_pes, [], current_pe)
    return {"symbol": symbol[:6], "pe_band": band.get("pe_band", {}),
            "updated_at": datetime.now().isoformat()}


@router.get("/{symbol}/pb-band")
async def get_pb_band(symbol: str):
    """PB Band 单独查询"""
    historical_pbs, current_pb = _fetch_pb_history(symbol)
    if not historical_pbs:
        return {"symbol": symbol[:6], "error": "PB历史数据不足"}
    band = fin_engine.pe_pb_band([], historical_pbs, None, current_pb)
    return {"symbol": symbol[:6], "pb_band": band.get("pb_band", {}),
            "updated_at": datetime.now().isoformat()}


def _fetch_pe_history(symbol: str) -> tuple:
    """获取历史PE数据"""
    from backend.shared.database import SessionLocal
    from backend.shared.models import FinancialReport

    db = SessionLocal()
    try:
        items = (
            db.query(FinancialReport)
            .filter(
                FinancialReport.stock_symbol == symbol[:6],
                FinancialReport.pe_ttm.isnot(None),
                FinancialReport.pe_ttm > 0,
            )
            .order_by(FinancialReport.report_date.desc())
            .limit(40)
            .all()
        )
        if not items:
            return [], None
        pes = [r.pe_ttm for r in items]
        return pes, items[0].pe_ttm
    finally:
        db.close()


def _fetch_pb_history(symbol: str) -> tuple:
    """获取历史PB数据"""
    from backend.shared.database import SessionLocal
    from backend.shared.models import FinancialReport

    db = SessionLocal()
    try:
        items = (
            db.query(FinancialReport)
            .filter(
                FinancialReport.stock_symbol == symbol[:6],
                FinancialReport.pb.isnot(None),
                FinancialReport.pb > 0,
            )
            .order_by(FinancialReport.report_date.desc())
            .limit(40)
            .all()
        )
        if not items:
            return [], None
        pbs = [r.pb for r in items]
        return pbs, items[0].pb
    finally:
        db.close()


def _fetch_reports(symbol: str) -> list[dict]:
    from backend.shared.database import SessionLocal
    from backend.shared.models import FinancialReport

    db = SessionLocal()
    try:
        items = (
            db.query(FinancialReport)
            .filter(FinancialReport.stock_symbol == symbol[:6])
            .order_by(FinancialReport.report_date.desc())
            .limit(2)
            .all()
        )
        return [
            {
                "total_assets": r.total_assets,
                "total_liabilities": r.total_liabilities,
                "total_equity": r.total_equity,
                "current_assets": r.current_assets,
                "current_liabilities": r.current_liabilities,
                "revenue": r.revenue,
                "net_profit": r.net_profit,
                "ebit": r.net_profit,  # 近似
            }
            for r in items
        ]
    finally:
        db.close()
