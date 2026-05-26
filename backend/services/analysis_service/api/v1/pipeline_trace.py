"""管道追踪查询 API"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.shared.database import get_db
from backend.shared.models import PipelineExecution, PipelineTrace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipeline", tags=["pipeline-observability"])


@router.get("/executions")
def list_executions(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """最近N天的管道执行记录"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(PipelineExecution)
        .filter(PipelineExecution.started_at >= since)
        .order_by(PipelineExecution.started_at.desc())
        .limit(50)
        .all()
    )

    return {
        "executions": [
            {
                "id": r.id,
                "execution_date": r.execution_date,
                "trigger_type": r.trigger_type,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "total_input": r.total_input,
                "total_output": r.total_output,
                "step_summary": r.step_summary,
                "error_message": r.error_message,
            }
            for r in rows
        ],
    }


@router.get("/executions/{execution_id}/traces")
def get_execution_traces(
    execution_id: str,
    step_name: str | None = Query(None),
    stock_code: str | None = Query(None),
    action: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """查询某次执行的追踪详情"""
    query = db.query(PipelineTrace).filter(PipelineTrace.execution_id == execution_id)

    if step_name:
        query = query.filter(PipelineTrace.step_name == step_name)
    if stock_code:
        query = query.filter(PipelineTrace.stock_code == stock_code)
    if action:
        query = query.filter(PipelineTrace.action == action)

    traces = query.order_by(PipelineTrace.step_order, PipelineTrace.stock_code).limit(2000).all()

    return {
        "execution_id": execution_id,
        "count": len(traces),
        "traces": [
            {
                "stock_code": t.stock_code,
                "stock_name": t.stock_name,
                "step_name": t.step_name,
                "step_order": t.step_order,
                "action": t.action,
                "score_before": t.score_before,
                "score_after": t.score_after,
                "reason": t.reason,
                "detail": t.detail,
            }
            for t in traces
        ],
    }


@router.get("/stock/{stock_code}/history")
def get_stock_pipeline_history(
    stock_code: str,
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """查询某只股票在最近N天管道中的经历"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(PipelineTrace, PipelineExecution.execution_date)
        .join(PipelineExecution, PipelineExecution.id == PipelineTrace.execution_id)
        .filter(PipelineTrace.stock_code == stock_code)
        .filter(PipelineExecution.started_at >= since)
        .order_by(PipelineExecution.execution_date.desc(), PipelineTrace.step_order.asc())
        .all()
    )

    return {
        "stock_code": stock_code,
        "count": len(rows),
        "history": [
            {
                "execution_id": t.execution_id,
                "execution_date": exec_date,
                "step_name": t.step_name,
                "step_order": t.step_order,
                "action": t.action,
                "score_before": t.score_before,
                "score_after": t.score_after,
                "reason": t.reason,
            }
            for t, exec_date in rows
        ],
    }
