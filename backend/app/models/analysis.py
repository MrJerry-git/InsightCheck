"""T04/T05：分析运行与跨系统候选结果。

一次分析运行固定决策日期、输入版本与规则版本；资料变化后旧结果标记为过期，
但仍可回看，不冒充最新结论。所有结论都是待复核的工程草稿。
"""

from datetime import date
from typing import Any

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin
from app.models.domain import enum_column
from app.models.enums import AnalysisStatus


class AnalysisRun(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        Index("ix_analysis_runs_patient_date", "patient_id", "as_of_date"),
    )

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[AnalysisStatus] = mapped_column(
        enum_column(AnalysisStatus, "analysis_status"), default=AnalysisStatus.COMPLETED
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    input_version: Mapped[str] = mapped_column(String(64))
    provider_version: Mapped[str] = mapped_column(String(64))
    rule_set_versions: Mapped[list[str]] = mapped_column(JSON, default=list)
    finding_map_version: Mapped[str] = mapped_column(String(64))
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    created_by_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
