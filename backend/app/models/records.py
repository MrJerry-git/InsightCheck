"""T02：业务记录的修订历史。

只保存结构化快照：变更前后字段、来源引用与操作账号。原始上传文件仍按现有边界
临时处理，不写入本表。
"""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin


class RecordRevision(IdMixin, CreatedAtMixin, Base):
    """一条业务记录的一次变更；按 entity_type + entity_id + revision_no 唯一。"""

    __tablename__ = "record_revisions"
    __table_args__ = (
        UniqueConstraint(
            "entity_type", "entity_id", "revision_no", name="uq_record_revision_number"
        ),
        Index("ix_record_revisions_patient_created", "patient_id", "created_at"),
    )

    patient_id: Mapped[str | None] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    changed_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32), default="manual", server_default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
