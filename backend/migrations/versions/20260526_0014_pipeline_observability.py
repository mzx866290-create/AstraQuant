"""Add pipeline_executions and pipeline_traces tables for observability.

Revision ID: 20260526_0014
Revises: 20260521_0013
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260526_0014"
down_revision = "20260521_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("execution_date", sa.String(10), nullable=False, index=True),
        sa.Column("trigger_type", sa.String(20), nullable=False, server_default="scheduled"),
        sa.Column("strategy_id", sa.String(50), nullable=True),
        sa.Column("market", sa.String(10), nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("total_input", sa.Integer, server_default="0"),
        sa.Column("total_output", sa.Integer, server_default="0"),
        sa.Column("step_summary", sa.JSON, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("execution_date", "trigger_type", "started_at", name="uix_pipeline_execution"),
    )
    op.create_index("ix_pipeline_executions_id", "pipeline_executions", ["id"])
    op.create_index("ix_pipeline_executions_execution_date", "pipeline_executions", ["execution_date"])
    op.create_index("ix_pipeline_executions_status", "pipeline_executions", ["status"])

    op.create_table(
        "pipeline_traces",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("pipeline_executions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("stock_code", sa.String(20), nullable=False, index=True),
        sa.Column("stock_name", sa.String(50), nullable=True),
        sa.Column("step_name", sa.String(50), nullable=False),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("score_before", sa.Float, nullable=True),
        sa.Column("score_after", sa.Float, nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("detail", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_pipeline_traces_id", "pipeline_traces", ["id"])
    op.create_index("ix_pipeline_traces_execution_id", "pipeline_traces", ["execution_id"])
    op.create_index("ix_pipeline_traces_stock_code", "pipeline_traces", ["stock_code"])
    op.create_index("ix_trace_exec_stock", "pipeline_traces", ["execution_id", "stock_code"])
    op.create_index("ix_trace_exec_step", "pipeline_traces", ["execution_id", "step_name"])


def downgrade() -> None:
    op.drop_index("ix_trace_exec_step", table_name="pipeline_traces")
    op.drop_index("ix_trace_exec_stock", table_name="pipeline_traces")
    op.drop_index("ix_pipeline_traces_stock_code", table_name="pipeline_traces")
    op.drop_index("ix_pipeline_traces_execution_id", table_name="pipeline_traces")
    op.drop_index("ix_pipeline_traces_id", table_name="pipeline_traces")
    op.drop_table("pipeline_traces")

    op.drop_index("ix_pipeline_executions_status", table_name="pipeline_executions")
    op.drop_index("ix_pipeline_executions_execution_date", table_name="pipeline_executions")
    op.drop_index("ix_pipeline_executions_id", table_name="pipeline_executions")
    op.drop_table("pipeline_executions")
