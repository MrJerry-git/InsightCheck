"""Add immutable synthetic import provenance."""

import sqlalchemy as sa

from alembic import op

revision = "d92a0175c310"
down_revision = "c61f42a9d807"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("payload_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("source_dataset", sa.String(64), nullable=False),
        sa.Column("source_version", sa.String(64), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("adapter_version", sa.String(64), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
    )
    op.create_table(
        "imported_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("import_batches.id"), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_imported_records_batch_id", "imported_records", ["batch_id"])


def downgrade() -> None:
    op.drop_table("imported_records")
    op.drop_table("import_batches")
