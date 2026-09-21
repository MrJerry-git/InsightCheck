"""T09/T10：报告导出记录与问答记录。"""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin


class ReportExport(IdMixin, CreatedAtMixin, Base):
    """一次报告导出：记录对应方案版本与内容摘要，便于追溯下载内容。"""

    __tablename__ = "report_exports"
    __table_args__ = (Index("ix_report_exports_plan", "plan_id", "revision_no"),)

    plan_id: Mapped[str] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer)
    report_format: Mapped[str] = mapped_column(String(16))
    content_sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_by_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )


class QaRecord(IdMixin, CreatedAtMixin, Base):
    """一次问答：保存问题、回答、引用与所用模式，便于复查与追溯。"""

    __tablename__ = "qa_records"
    __table_args__ = (Index("ix_qa_records_patient_created", "patient_id", "created_at"),)

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    plan_revision_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(64))
    model_status: Mapped[str] = mapped_column(String(200))
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    request_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    created_by_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
