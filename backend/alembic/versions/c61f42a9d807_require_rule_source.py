"""require nonblank medical rule source

Revision ID: c61f42a9d807
Revises: 8d4c7a12e3f9
Create Date: 2026-08-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c61f42a9d807"
down_revision: str | None = "8d4c7a12e3f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("medical_rules", recreate="always") as batch_op:
        batch_op.create_check_constraint("source_nonempty", "length(trim(source)) > 0")


def downgrade() -> None:
    with op.batch_alter_table("medical_rules", recreate="always") as batch_op:
        batch_op.drop_constraint(op.f("ck_medical_rules_source_nonempty"), type_="check")
