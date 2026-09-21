"""账号与会话模型。

密码只保存 PBKDF2 派生结果（盐值与迭代次数随记录保存，便于日后升级算法）；
会话只保存令牌的 SHA-256 摘要，明文令牌只在登录响应里出现一次。
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin
from app.models.domain import enum_column
from app.models.enums import AccountRole


class Account(IdMixin, CreatedAtMixin, Base):
    """登录账号；与受检者档案分开，档案通过 owner_account_id 归属账号。"""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("length(username) >= 3", name="username_min_length"),
        CheckConstraint("length(password_hash) >= 32", name="password_hash_present"),
        CheckConstraint("password_iterations >= 10000", name="password_iterations_minimum"),
    )

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[AccountRole] = mapped_column(
        enum_column(AccountRole, "account_role"), default=AccountRole.DOCTOR
    )
    password_hash: Mapped[str] = mapped_column(String(128))
    password_salt: Mapped[str] = mapped_column(String(64))
    password_iterations: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )


class AuthSession(IdMixin, CreatedAtMixin, Base):
    """一次登录产生的会话；退出即写入 revoked_at，过期时间固定不变。"""

    __tablename__ = "auth_sessions"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    account: Mapped[Account] = relationship(back_populates="sessions")
