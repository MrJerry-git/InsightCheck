"""T06/T07: plans, price snapshots and immutable revisions.

Revision ID: d5e93b7c2f31
Revises: c4d8e21f9a10
Create Date: 2026-09-21 15:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "d5e93b7c2f31"
down_revision = "c4d8e21f9a10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "patient_id",
            sa.String(36),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "analysis_run_id",
            sa.String(36),
            sa.ForeignKey("analysis_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("current_snapshot", sa.JSON(), nullable=True),
        sa.Column("price_catalog_version", sa.String(64), nullable=True),
        sa.Column("budget_limit_cents", sa.Integer(), nullable=True),
        sa.Column("budget_currency", sa.String(8), nullable=True),
        sa.Column("institution", sa.String(200), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("request_id", sa.String(80), nullable=True, unique=True),
        sa.Column(
            "created_by_account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'review', 'confirmed')", name=op.f("ck_plans_plan_status")
        ),
        sa.CheckConstraint(
            "budget_limit_cents IS NULL OR budget_limit_cents >= 0",
            name=op.f("ck_plans_budget_non_negative"),
        ),
    )
    op.create_index("ix_plans_patient_id", "plans", ["patient_id"])
    op.create_index("ix_plans_analysis_run_id", "plans", ["analysis_run_id"])
    op.create_index("ix_plans_as_of_date", "plans", ["as_of_date"])
    op.create_index("ix_plans_created_by_account_id", "plans", ["created_by_account_id"])
    op.create_index("ix_plans_patient_status", "plans", ["patient_id", "status"])

    op.create_table(
        "plan_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "plan_id", sa.String(36), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("action", sa.String(32), server_default="create", nullable=False),
        sa.Column("analysis_run_id", sa.String(36), nullable=True),
        sa.Column("price_catalog_version", sa.String(64), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_by_account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("plan_id", "revision_no", name="uq_plan_revision_number"),
    )
    op.create_index("ix_plan_revisions_plan_id", "plan_revisions", ["plan_id"])
    op.create_index(
        "ix_plan_revisions_plan_revision", "plan_revisions", ["plan_id", "revision_no"]
    )


def downgrade() -> None:
    op.drop_index("ix_plan_revisions_plan_revision", table_name="plan_revisions")
    op.drop_index("ix_plan_revisions_plan_id", table_name="plan_revisions")
    op.drop_table("plan_revisions")
    op.drop_index("ix_plans_patient_status", table_name="plans")
    op.drop_index("ix_plans_created_by_account_id", table_name="plans")
    op.drop_index("ix_plans_as_of_date", table_name="plans")
    op.drop_index("ix_plans_analysis_run_id", table_name="plans")
    op.drop_index("ix_plans_patient_id", table_name="plans")
    op.drop_table("plans")
