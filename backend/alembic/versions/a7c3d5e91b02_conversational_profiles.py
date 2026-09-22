"""Add conversational profile, session, draft, action and snapshot tables.

挂载点：T 链 head ``a1f7c3b90d42``（报告证据快照）。参赛版与 2.0 使用同一条
迁移链：T 系列先合并，本 PR 以 T 链为基底，避免出现两个 alembic head。
"""
import sqlalchemy as sa

from alembic import op

revision = "a7c3d5e91b02"
down_revision = "a1f7c3b90d42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("confirmed", sa.JSON(), nullable=True),
        sa.Column("analysis_stale", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("owner_account_id", sa.String(36),
                  sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_profiles_owner_account_id", "profiles", ["owner_account_id"])
    op.create_table(
        "profile_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("profile_id", sa.String(36),
                  sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("missing", sa.JSON(), nullable=True),
        sa.Column("questions", sa.JSON(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_profile_drafts_profile_id", "profile_drafts", ["profile_id"],
                    unique=True)
    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("profile_id", sa.String(36),
                  sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_conversation_sessions_profile_id", "conversation_sessions",
                    ["profile_id"], unique=False)
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("profile_id", sa.String(36),
                  sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(36),
                  sa.ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
    )
    op.create_index("ix_conversation_messages_profile_id", "conversation_messages",
                    ["profile_id"], unique=False)
    op.create_index("ix_conversation_messages_session_id", "conversation_messages",
                    ["session_id"], unique=False)
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("profile_id", sa.String(36),
                  sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(36),
                  sa.ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pending_actions_profile_id", "pending_actions", ["profile_id"],
                    unique=False)
    op.create_index("ix_pending_actions_session_id", "pending_actions", ["session_id"],
                    unique=False)
    op.create_index("ix_pending_actions_status", "pending_actions", ["status"],
                    unique=False)
    op.create_table(
        "action_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("profile_id", sa.String(36),
                  sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("op_id", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("request", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("undoable", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("undone", sa.Boolean(), server_default="0", nullable=False),
        sa.UniqueConstraint("profile_id", "op_id", name="uq_action_logs_profile_op"),
    )
    op.create_index("ix_action_logs_profile_id", "action_logs", ["profile_id"],
                    unique=False)
    op.create_table(
        "archive_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("profile_id", sa.String(36),
                  sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), server_default="current", nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
    )
    op.create_index("ix_archive_snapshots_profile_id", "archive_snapshots",
                    ["profile_id"], unique=False)
    op.create_index("ix_archive_snapshots_status", "archive_snapshots", ["status"],
                    unique=False)


def downgrade():
    op.drop_index("ix_archive_snapshots_status", table_name="archive_snapshots")
    op.drop_index("ix_archive_snapshots_profile_id", table_name="archive_snapshots")
    op.drop_table("archive_snapshots")
    op.drop_index("ix_action_logs_profile_id", table_name="action_logs")
    op.drop_table("action_logs")
    op.drop_index("ix_pending_actions_status", table_name="pending_actions")
    op.drop_index("ix_pending_actions_session_id", table_name="pending_actions")
    op.drop_index("ix_pending_actions_profile_id", table_name="pending_actions")
    op.drop_table("pending_actions")
    op.drop_index("ix_conversation_messages_session_id", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_profile_id", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversation_sessions_profile_id", table_name="conversation_sessions")
    op.drop_table("conversation_sessions")
    op.drop_index("ix_profile_drafts_profile_id", table_name="profile_drafts")
    op.drop_table("profile_drafts")
    op.drop_index("ix_profiles_owner_account_id", table_name="profiles")
    op.drop_table("profiles")
