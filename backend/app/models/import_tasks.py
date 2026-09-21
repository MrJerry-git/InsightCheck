"""T03：文件导入任务。

任务保存解析进度、逐字段校对结果与错误，原始文件只做临时存放（确认或取消后删除），
不进入长期归档。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin
from app.models.domain import enum_column
from app.models.enums import ImportTaskStatus


class ImportTask(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "import_tasks"
    __table_args__ = (
        Index("ix_import_tasks_patient_status", "patient_id", "status"),
        Index("ix_import_tasks_payload", "patient_id", "payload_sha256"),
    )

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[ImportTaskStatus] = mapped_column(
        enum_column(ImportTaskStatus, "import_task_status"), default=ImportTaskStatus.UPLOADED
    )
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    payload_sha256: Mapped[str] = mapped_column(String(64), index=True)
    parser: Mapped[str] = mapped_column(String(32), default="tabular")
    request_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    temporary_path: Mapped[str | None] = mapped_column(String(400), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    draft: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duplicate_of_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    confirmed_by_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
