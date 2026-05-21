"""Add v3 pipeline tables: financial_trends, rejection_logs, and extra columns."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260515_0009"
down_revision = "20260514_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- new tables -----------------------------------------------------------
    op.create_table(
        "financial_trends",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stock_code", sa.String(20), nullable=False, index=True),
        sa.Column("report_date", sa.String(10), nullable=False),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.Column("revenue_yoy", sa.Float(), nullable=True),
        sa.Column("net_profit", sa.Float(), nullable=True),
        sa.Column("profit_yoy", sa.Float(), nullable=True),
        sa.Column("operating_cashflow", sa.Float(), nullable=True),
        sa.Column("roe", sa.Float(), nullable=True),
        sa.Column("revenue_decline_quarters", sa.Integer(), server_default="0"),
        sa.Column("profit_decline_quarters", sa.Integer(), server_default="0"),
        sa.Column("cashflow_negative_quarters", sa.Integer(), server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("stock_code", "report_date", name="uix_financial_trend"),
    )

    op.create_table(
        "rejection_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(20), nullable=False, index=True),
        sa.Column("stock_name", sa.String(50), nullable=True),
        sa.Column("trade_date", sa.String(10), nullable=False, index=True),
        sa.Column("reject_stage", sa.String(30), nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("reject_detail", sa.JSON(), nullable=True),
        sa.Column("base_score", sa.Float(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("almost_qualified", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_rejection_logs_trade_date_almost_qualified",
        "rejection_logs",
        ["trade_date", "almost_qualified"],
    )

    # --- add columns to pipeline_run_logs ------------------------------------
    with op.batch_alter_table("pipeline_run_logs") as batch_op:
        batch_op.add_column(sa.Column("industries_collected", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("after_screening", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("after_hard_veto", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("after_scoring", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("vetoed_by_industry", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("vetoed_by_acceleration", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("vetoed_by_peer", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("vetoed_by_fundamental", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("vetoed_by_valuation", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("vetoed_by_risk", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("duration_seconds", sa.Integer(), nullable=True))

    # --- add columns to industry_health_scores -------------------------------
    with op.batch_alter_table("industry_health_scores") as batch_op:
        batch_op.add_column(sa.Column("score_5d_ago", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("score_change_5d", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("is_accelerating_down", sa.Boolean(), server_default=sa.text("false"))
        )


def downgrade() -> None:
    # --- remove columns from industry_health_scores --------------------------
    with op.batch_alter_table("industry_health_scores") as batch_op:
        batch_op.drop_column("is_accelerating_down")
        batch_op.drop_column("score_change_5d")
        batch_op.drop_column("score_5d_ago")

    # --- remove columns from pipeline_run_logs -------------------------------
    with op.batch_alter_table("pipeline_run_logs") as batch_op:
        batch_op.drop_column("duration_seconds")
        batch_op.drop_column("vetoed_by_risk")
        batch_op.drop_column("vetoed_by_valuation")
        batch_op.drop_column("vetoed_by_fundamental")
        batch_op.drop_column("vetoed_by_peer")
        batch_op.drop_column("vetoed_by_acceleration")
        batch_op.drop_column("vetoed_by_industry")
        batch_op.drop_column("after_scoring")
        batch_op.drop_column("after_hard_veto")
        batch_op.drop_column("after_screening")
        batch_op.drop_column("industries_collected")

    # --- drop new tables -----------------------------------------------------
    op.drop_index("ix_rejection_logs_trade_date_almost_qualified", table_name="rejection_logs")
    op.drop_table("rejection_logs")
    op.drop_table("financial_trends")
