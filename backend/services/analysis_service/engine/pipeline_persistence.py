"""管道追踪数据持久化"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from backend.shared.database import SessionLocal
from backend.shared.models import PipelineExecution, PipelineTrace

logger = logging.getLogger(__name__)


def create_execution_record(ctx) -> str:
    """在管道开始时创建 pipeline_executions 记录，返回 execution_id"""
    db = SessionLocal()
    try:
        record = PipelineExecution(
            id=ctx.execution_id,
            execution_date=ctx.execution_date,
            trigger_type=ctx.trigger_type,
            strategy_id=ctx.strategy_id or None,
            market=ctx.market or None,
            started_at=ctx.started_at,
            status="running",
        )
        db.add(record)
        db.commit()
        logger.info("Pipeline execution record created: %s", ctx.execution_id)
        return ctx.execution_id
    except Exception as e:
        logger.warning("Failed to create execution record: %s", e)
        db.rollback()
        return ctx.execution_id
    finally:
        db.close()


def complete_execution_record(ctx, *, status: str, error: str | None = None,
                              total_input: int = 0, total_output: int = 0):
    """在管道结束时更新 pipeline_executions 记录"""
    db = SessionLocal()
    try:
        record = db.query(PipelineExecution).filter_by(id=ctx.execution_id).first()
        if record:
            record.finished_at = datetime.now(timezone.utc)
            record.status = status
            record.total_input = total_input
            record.total_output = total_output
            record.step_summary = ctx.step_stats
            record.error_message = error[:500] if error else None
            db.commit()
            logger.info("Pipeline execution completed: %s status=%s output=%d", ctx.execution_id, status, total_output)
        else:
            logger.warning("Pipeline execution record not found: %s", ctx.execution_id)
    except Exception as e:
        logger.warning("Failed to complete execution record: %s", e)
        db.rollback()
    finally:
        db.close()


def save_traces(ctx, *, batch_size: int = 500):
    """批量保存管道追踪数据到 pipeline_traces 表"""
    total = ctx.total_traces()
    if total == 0:
        return

    db = SessionLocal()
    try:
        count = 0
        _STEP_ORDER = {
            "collect": 1, "screen_anomalies": 2, "industry_filter": 3,
            "hard_veto": 4, "base_score": 5, "multiplier_score": 6,
            "capital_flow": 7, "chase_high_penalty": 8, "risk_veto": 9,
            "tier_classify": 10, "observation_actions": 11, "pool_optimizer": 12,
        }
        for step_name, traces in ctx.traces.items():
            order = _STEP_ORDER.get(step_name, 99)

            for t in traces:
                record = PipelineTrace(
                    execution_id=ctx.execution_id,
                    stock_code=t.stock_code,
                    stock_name=t.stock_name,
                    step_name=step_name,
                    step_order=order,
                    action=t.action,
                    score_before=t.score_before,
                    score_after=t.score_after,
                    reason=t.reason[:500] if t.reason else None,
                    detail=t.detail,
                )
                db.add(record)
                count += 1

                if count % batch_size == 0:
                    db.flush()

        db.commit()
        logger.info("Saved %d pipeline traces for execution %s", count, ctx.execution_id)
    except Exception as e:
        logger.warning("Failed to save pipeline traces: %s", e)
        db.rollback()
    finally:
        db.close()
