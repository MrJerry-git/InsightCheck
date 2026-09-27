"""T09/T10: report exports and QA records.

Revision ID: f7a1526b9c83
Revises: e6f0451a8b72
Create Date: 2026-09-21 17:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "f7a1526b9c83"
down_revision = "e6f0451a8b72"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_exports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "plan_id", sa.String(36), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("report_format", sa.String(16), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_by_account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_report_exports_plan_id", "report_exports", ["plan_id"])
    op.create_index("ix_report_exports_plan", "report_exports", ["plan_id", "revision_no"])

    op.create_table(
        "qa_records",
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
            "plan_id", sa.String(36), sa.ForeignKey("plans.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("plan_revision_no", sa.Integer(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_status", sa.String(200), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(80), nullable=True, unique=True),
        sa.Column(
            "created_by_account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_qa_records_patient_id", "qa_records", ["patient_id"])
    op.create_index("ix_qa_records_plan_id", "qa_records", ["plan_id"])
    op.create_index("ix_qa_records_patient_created", "qa_records", ["patient_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_qa_records_patient_created", table_name="qa_records")
    op.drop_index("ix_qa_records_plan_id", table_name="qa_records")
    op.drop_index("ix_qa_records_patient_id", table_name="qa_records")
    op.drop_table("qa_records")
    op.drop_index("ix_report_exports_plan", table_name="report_exports")
    op.drop_index("ix_report_exports_plan_id", table_name="report_exports")
    op.drop_table("report_exports")
