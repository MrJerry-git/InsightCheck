from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin


class PreventionReport(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "prevention_reports"
    label: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    # T01：参赛报告归属账号；为空表示历史/演示报告，仅管理员可见。
    owner_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
