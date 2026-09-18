"""Add exam item price records for plan budget calculation.

Revision ID: b7e4c1a920d3
Revises: d92a0175c310
Create Date: 2026-09-18 10:40:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "b7e4c1a920d3"
down_revision = "d92a0175c310"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_item_prices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "exam_item_id",
            sa.String(36),
            sa.ForeignKey("exam_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="CNY", nullable=False),
        sa.Column("source", sa.String(300), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("institution", sa.String(200), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_demo_price", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "amount_cents >= 0", name=op.f("ck_exam_item_prices_amount_cents_non_negative")
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name=op.f("ck_exam_item_prices_effective_range_order"),
        ),
        sa.CheckConstraint(
            "is_demo_price OR source_url IS NOT NULL",
            name=op.f("ck_exam_item_prices_real_price_requires_source_url"),
        ),
    )
    op.create_index("ix_exam_item_prices_effective_from", "exam_item_prices", ["effective_from"])
    op.create_index("ix_exam_item_prices_exam_item_id", "exam_item_prices", ["exam_item_id"])


def downgrade() -> None:
    op.drop_index("ix_exam_item_prices_exam_item_id", table_name="exam_item_prices")
    op.drop_index("ix_exam_item_prices_effective_from", table_name="exam_item_prices")
    op.drop_table("exam_item_prices")
