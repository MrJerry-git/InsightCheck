"""Add accounts, auth sessions and patient ownership (T01).

Revision ID: e5b17c9a2d40
Revises: e021a0b10001（PREVENT 报告迁移之后的当前 head）
Create Date: 2026-09-20 10:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "e5b17c9a2d40"
down_revision = "e021a0b10001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "admin",
                "doctor",
                "viewer",
                name="account_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("password_salt", sa.String(64), nullable=False),
        sa.Column("password_iterations", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(username) >= 3", name=op.f("ck_accounts_username_min_length")),
        sa.CheckConstraint(
            "length(password_hash) >= 32", name=op.f("ck_accounts_password_hash_present")
        ),
        sa.CheckConstraint(
            "password_iterations >= 10000",
            name=op.f("ck_accounts_password_iterations_minimum"),
        ),
    )
    op.create_index("ix_accounts_username", "accounts", ["username"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_sessions_account_id", "auth_sessions", ["account_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"])

    # SQLite 不支持 ALTER 加外键，批量模式会重建 patients 表。
    with op.batch_alter_table("patients") as batch:
        batch.add_column(sa.Column("owner_account_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_patients_owner_account_id_accounts",
            "accounts",
            ["owner_account_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_patients_owner_account_id", ["owner_account_id"])


def downgrade() -> None:
    with op.batch_alter_table("patients") as batch:
        batch.drop_index("ix_patients_owner_account_id")
        batch.drop_constraint("fk_patients_owner_account_id_accounts", type_="foreignkey")
        batch.drop_column("owner_account_id")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_account_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_accounts_username", table_name="accounts")
    op.drop_table("accounts")
