"""T01: competition reports carry the owning account.

参赛报告加入归属账号，使 /prevention/reports 在启用鉴权后按账号隔离；
历史行为空的报告视为演示数据，只对管理员开放。
"""

import sqlalchemy as sa

from alembic import op

revision = "c3d8f0a41b27"
down_revision = "e5b17c9a2d40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("prevention_reports") as batch:
        batch.add_column(sa.Column("owner_account_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_prevention_reports_owner_account_id",
            "accounts",
            ["owner_account_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_prevention_reports_owner_account_id", ["owner_account_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("prevention_reports") as batch:
        batch.drop_index("ix_prevention_reports_owner_account_id")
        batch.drop_constraint("fk_prevention_reports_owner_account_id", type_="foreignkey")
        batch.drop_column("owner_account_id")
