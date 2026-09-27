"""T08: admin audit events.

Revision ID: e6f0451a8b72
Revises: d5e93b7c2f31
Create Date: 2026-09-21 16:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "e6f0451a8b72"
down_revision = "d5e93b7c2f31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "actor_account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_username", sa.String(64), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column(
            "patient_id",
            sa.String(36),
            sa.ForeignKey("patients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
    )
    op.create_index("ix_audit_events_actor_account_id", "audit_events", ["actor_account_id"])
    op.create_index("ix_audit_events_patient_id", "audit_events", ["patient_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_entity_type", "audit_events", ["entity_type"])
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])
    op.create_index(
        "ix_audit_events_actor_created", "audit_events", ["actor_account_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_actor_created", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_type", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_patient_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_account_id", table_name="audit_events")
    op.drop_table("audit_events")
