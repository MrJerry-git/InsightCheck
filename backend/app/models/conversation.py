"""对话式档案管理持久化模型。

只保存结构化草稿、已确认资料、消息与操作日志；原始上传文件按现有 smart-import
边界在内存中处理，不写入会话数据库。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin


class Profile(IdMixin, CreatedAtMixin, Base):
    """独立体检档案：一个人一份，禁止跨人自动合并。"""

    __tablename__ = "profiles"

    display_name: Mapped[str] = mapped_column(String(120))
    # 已确认资料的版本号：确认/撤销生效时 +1；仅修改草稿不改变。
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    confirmed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_stale: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # 归属账号：与 patients.owner_account_id 同一套权限语义（T01）。
    owner_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProfileDraft(IdMixin, CreatedAtMixin, Base):
    """未确认草稿：每个档案一份，未确认前不点亮人体、不影响规划。"""

    __tablename__ = "profile_drafts"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), unique=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    missing: Mapped[list] = mapped_column(JSON, default=list)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ConversationSession(IdMixin, CreatedAtMixin, Base):
    """一次工作区会话；新建档案或“重新开始整理”都会开启新会话。"""

    __tablename__ = "conversation_sessions"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationMessage(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "conversation_messages"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PendingAction(IdMixin, CreatedAtMixin, Base):
    """待确认/待追问动作：open -> resolved | cancelled | expired。"""

    __tablename__ = "pending_actions"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open",
                                        index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActionLog(IdMixin, CreatedAtMixin, Base):
    """幂等键 (profile_id, op_id)、真实变更摘要与撤销上下文。"""

    __tablename__ = "action_logs"
    __table_args__ = (UniqueConstraint("profile_id", "op_id", name="uq_action_logs_profile_op"),)

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    op_id: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(32))
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    # 撤销上下文：本次操作前的档案状态（已确认资料/草稿/版本），不跨档案使用。
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    undoable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    undone: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class ArchiveSnapshot(IdMixin, CreatedAtMixin, Base):
    """不可变规划快照：绑定档案版本，旧版本置 stale 仍可只读回看。"""

    __tablename__ = "archive_snapshots"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="current",
                                        server_default="current", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
