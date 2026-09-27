"""冻结报告证据快照（T09 审核 P1）。

历史报告与问答必须读取生成时的依据，而不是当前 LabMetric/MedicalRule。
"""

import sqlalchemy as sa

from alembic import op

revision = "a1f7c3b90d42"
down_revision = "f7a1526b9c83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_evidence_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("plan_id", "revision_no", name="uq_report_evidence_plan_revision"),
    )
    op.create_index(
        "ix_report_evidence_snapshots_plan_id", "report_evidence_snapshots", ["plan_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_report_evidence_snapshots_plan_id", table_name="report_evidence_snapshots")
    op.drop_table("report_evidence_snapshots")
