"""T06/T07：三档方案、价格快照与修订版本。

方案依赖一次分析运行（T04）与价格目录：每次修改都重新执行规则与费用计算，
并把结果固化成不可改写的修订快照；之后调整价格或规则不改变已保存的修订。
"""

from datetime import date
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin
from app.models.domain import enum_column
from app.models.enums import PlanStatus


class Plan(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (Index("ix_plans_patient_status", "patient_id", "status"),)

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[PlanStatus] = mapped_column(
        enum_column(PlanStatus, "plan_status"), default=PlanStatus.DRAFT
    )
    revision_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    current_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    price_catalog_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    budget_limit_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    institution: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    created_by_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )

    revisions: Mapped[list["PlanRevision"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", passive_deletes=True
    )


class PlanRevision(IdMixin, CreatedAtMixin, Base):
    """不可改写的方案版本：保存当时的输入、价格快照与三档结果。"""

    __tablename__ = "plan_revisions"
    __table_args__ = (
        Index("ix_plan_revisions_plan_revision", "plan_id", "revision_no"),
    )

    plan_id: Mapped[str] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(32), default="create")
    analysis_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    price_catalog_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    plan: Mapped[Plan] = relationship(back_populates="revisions")
