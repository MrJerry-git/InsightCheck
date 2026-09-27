"""T04/T05: analysis runs with fixed decision date and input version.

Revision ID: c4d8e21f9a10
Revises: b3c1d9e77a45
Create Date: 2026-09-21 14:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "c4d8e21f9a10"
down_revision = "b3c1d9e77a45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
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
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_version", sa.String(64), nullable=False),
        sa.Column("provider_version", sa.String(64), nullable=False),
        sa.Column("rule_set_versions", sa.JSON(), nullable=True),
        sa.Column("finding_map_version", sa.String(64), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=True),
        sa.Column("candidates", sa.JSON(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("notes", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(80), nullable=True, unique=True),
        sa.Column(
            "created_by_account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_demo", sa.Boolean(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck_analysis_runs_analysis_status"),
        ),
    )
    op.create_index("ix_analysis_runs_patient_id", "analysis_runs", ["patient_id"])
    op.create_index("ix_analysis_runs_as_of_date", "analysis_runs", ["as_of_date"])
    op.create_index(
        "ix_analysis_runs_created_by_account_id", "analysis_runs", ["created_by_account_id"]
    )
    op.create_index(
        "ix_analysis_runs_patient_date", "analysis_runs", ["patient_id", "as_of_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_patient_date", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_created_by_account_id", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_as_of_date", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_patient_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")
