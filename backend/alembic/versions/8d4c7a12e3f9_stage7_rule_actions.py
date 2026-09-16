"""stage 7 medical rule actions

Revision ID: 8d4c7a12e3f9
Revises: 0311597601c8
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8d4c7a12e3f9"
down_revision: str | None = "0311597601c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTIONS = ("include", "exclude", "adjust_score", "require_review")
NEW_ACTIONS = ("ALLOW", "BOOST", "REDUCE", "DEFER", "BLOCK", "REVIEW_REQUIRED")


def _replace_action_column(
    *,
    source_values: tuple[str, ...],
    target_values: tuple[str, ...],
    mapping_sql: str,
) -> None:
    old_enum = sa.Enum(
        *source_values,
        name="rule_action",
        native_enum=False,
        create_constraint=True,
    )
    new_enum = sa.Enum(
        *target_values,
        name="rule_action",
        native_enum=False,
        create_constraint=True,
    )
    op.add_column("medical_rules", sa.Column("action_v2", sa.String(length=32), nullable=True))
    op.execute(sa.text(f"UPDATE medical_rules SET action_v2 = {mapping_sql}"))
    with op.batch_alter_table("medical_rules", recreate="always") as batch_op:
        batch_op.drop_constraint(op.f("ck_medical_rules_rule_action"), type_="check")
        batch_op.drop_column("action", existing_type=old_enum)
        batch_op.alter_column(
            "action_v2",
            new_column_name="action",
            existing_type=sa.String(length=32),
            type_=new_enum,
            nullable=False,
        )


def upgrade() -> None:
    _replace_action_column(
        source_values=OLD_ACTIONS,
        target_values=NEW_ACTIONS,
        mapping_sql=(
            "CASE action "
            "WHEN 'include' THEN 'ALLOW' "
            "WHEN 'exclude' THEN 'BLOCK' "
            "WHEN 'adjust_score' THEN 'REVIEW_REQUIRED' "
            "WHEN 'require_review' THEN 'REVIEW_REQUIRED' "
            "ELSE 'REVIEW_REQUIRED' END"
        ),
    )


def downgrade() -> None:
    _replace_action_column(
        source_values=NEW_ACTIONS,
        target_values=OLD_ACTIONS,
        mapping_sql=(
            "CASE action "
            "WHEN 'ALLOW' THEN 'include' "
            "WHEN 'BLOCK' THEN 'exclude' "
            "WHEN 'BOOST' THEN 'adjust_score' "
            "WHEN 'REDUCE' THEN 'adjust_score' "
            "WHEN 'DEFER' THEN 'require_review' "
            "WHEN 'REVIEW_REQUIRED' THEN 'require_review' "
            "ELSE 'require_review' END"
        ),
    )
