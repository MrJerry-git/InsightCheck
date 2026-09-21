"""T02: record revisions, metric value types and record provenance.

Revision ID: f2a7c4d10e88
Revises: c3d8f0a41b27（T01 账号迁移 + 参赛报告归属）
Create Date: 2026-09-21 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "f2a7c4d10e88"
down_revision = "c3d8f0a41b27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "record_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "patient_id",
            sa.String(36),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("source_kind", sa.String(32), server_default="manual", nullable=False),
        sa.Column("source_ref", sa.String(200), nullable=True),
        sa.Column(
            "actor_account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.String(300), nullable=True),
        sa.UniqueConstraint(
            "entity_type", "entity_id", "revision_no", name="uq_record_revision_number"
        ),
    )
    op.create_index("ix_record_revisions_patient_id", "record_revisions", ["patient_id"])
    op.create_index("ix_record_revisions_entity_type", "record_revisions", ["entity_type"])
    op.create_index("ix_record_revisions_entity_id", "record_revisions", ["entity_id"])
    op.create_index(
        "ix_record_revisions_actor_account_id", "record_revisions", ["actor_account_id"]
    )
    op.create_index(
        "ix_record_revisions_patient_created", "record_revisions", ["patient_id", "created_at"]
    )

    dialect = op.get_bind().dialect.name
    # 旧记录兼容：来源标记为 manual，修订号从 1 开始；旧指标按数值型读取。
    with op.batch_alter_table("health_checks") as batch:
        batch.add_column(
            sa.Column("source_kind", sa.String(32), server_default="manual", nullable=False)
        )
        batch.add_column(sa.Column("source_ref", sa.String(200), nullable=True))
        batch.add_column(
            sa.Column("revision_no", sa.Integer(), server_default="1", nullable=False)
        )
        batch.create_index("ix_health_checks_source_kind", ["source_kind"])
    with op.batch_alter_table("lab_metrics") as batch:
        batch.add_column(
            sa.Column("source_kind", sa.String(32), server_default="manual", nullable=False)
        )
        batch.add_column(sa.Column("source_ref", sa.String(200), nullable=True))
        batch.add_column(
            sa.Column("revision_no", sa.Integer(), server_default="1", nullable=False)
        )
        batch.add_column(sa.Column("qualitative_value", sa.String(100), nullable=True))
        batch.add_column(
            sa.Column("value_type", sa.String(16), server_default="numeric", nullable=False)
        )
        if dialect != "postgresql":
            batch.create_check_constraint(
                "ck_lab_metrics_lab_metric_value_type",
                "value_type IN ('numeric', 'qualitative', 'text')",
            )
        batch.create_index("ix_lab_metrics_source_kind", ["source_kind"])
    with op.batch_alter_table("imaging_exams") as batch:
        batch.add_column(
            sa.Column("source_kind", sa.String(32), server_default="manual", nullable=False)
        )
        batch.add_column(sa.Column("source_ref", sa.String(200), nullable=True))
        batch.add_column(
            sa.Column("revision_no", sa.Integer(), server_default="1", nullable=False)
        )
        batch.create_index("ix_imaging_exams_source_kind", ["source_kind"])
    with op.batch_alter_table("metric_dictionaries") as batch:
        batch.add_column(
            sa.Column("value_type", sa.String(16), server_default="numeric", nullable=False)
        )

    # 已有记录统一回填，保证旧数据在"修订历史"视图下也有起点。
    op.execute("UPDATE lab_metrics SET value_type = 'numeric' WHERE value_type IS NULL")
    op.execute("UPDATE health_checks SET source_kind = 'manual', revision_no = 1")
    op.execute("UPDATE lab_metrics SET source_kind = 'manual', revision_no = 1")
    op.execute("UPDATE imaging_exams SET source_kind = 'manual', revision_no = 1")


def downgrade() -> None:
    with op.batch_alter_table("metric_dictionaries") as batch:
        batch.drop_column("value_type")
    with op.batch_alter_table("imaging_exams") as batch:
        batch.drop_index("ix_imaging_exams_source_kind")
        batch.drop_column("revision_no")
        batch.drop_column("source_ref")
        batch.drop_column("source_kind")
    with op.batch_alter_table("lab_metrics") as batch:
        batch.drop_index("ix_lab_metrics_source_kind")
        batch.drop_column("value_type")
        batch.drop_column("qualitative_value")
        batch.drop_column("revision_no")
        batch.drop_column("source_ref")
        batch.drop_column("source_kind")
    with op.batch_alter_table("health_checks") as batch:
        batch.drop_index("ix_health_checks_source_kind")
        batch.drop_column("revision_no")
        batch.drop_column("source_ref")
        batch.drop_column("source_kind")
    op.drop_index("ix_record_revisions_patient_created", table_name="record_revisions")
    op.drop_index("ix_record_revisions_actor_account_id", table_name="record_revisions")
    op.drop_index("ix_record_revisions_entity_id", table_name="record_revisions")
    op.drop_index("ix_record_revisions_entity_type", table_name="record_revisions")
    op.drop_index("ix_record_revisions_patient_id", table_name="record_revisions")
    op.drop_table("record_revisions")
