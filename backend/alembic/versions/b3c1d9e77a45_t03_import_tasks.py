"""T03: import task queue with preview and confirmation.

Revision ID: b3c1d9e77a45
Revises: f2a7c4d10e88
Create Date: 2026-09-21 13:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "b3c1d9e77a45"
down_revision = "f2a7c4d10e88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_tasks",
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
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("parser", sa.String(32), server_default="tabular", nullable=False),
        sa.Column("request_id", sa.String(80), nullable=True, unique=True),
        sa.Column("temporary_path", sa.String(400), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("draft", sa.JSON(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duplicate_of_task_id", sa.String(36), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "confirmed_by_account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "status IN ('uploaded', 'parsing', 'preview_ready', 'failed', 'confirmed', "
            "'cancelled')",
            name=op.f("ck_import_tasks_import_task_status"),
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_import_tasks_size_positive")),
    )
    op.create_index("ix_import_tasks_patient_id", "import_tasks", ["patient_id"])
    op.create_index("ix_import_tasks_payload_sha256", "import_tasks", ["payload_sha256"])
    op.create_index(
        "ix_import_tasks_created_by_account_id", "import_tasks", ["created_by_account_id"]
    )
    op.create_index("ix_import_tasks_patient_status", "import_tasks", ["patient_id", "status"])
    op.create_index("ix_import_tasks_payload", "import_tasks", ["patient_id", "payload_sha256"])


def downgrade() -> None:
    op.drop_index("ix_import_tasks_payload", table_name="import_tasks")
    op.drop_index("ix_import_tasks_patient_status", table_name="import_tasks")
    op.drop_index("ix_import_tasks_created_by_account_id", table_name="import_tasks")
    op.drop_index("ix_import_tasks_payload_sha256", table_name="import_tasks")
    op.drop_index("ix_import_tasks_patient_id", table_name="import_tasks")
    op.drop_table("import_tasks")
