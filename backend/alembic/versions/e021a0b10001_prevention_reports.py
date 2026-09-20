"""Persist immutable competition report snapshots."""
import sqlalchemy as sa

from alembic import op

revision = "e021a0b10001"
down_revision = "b7e4c1a920d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "prevention_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("prevention_reports")
