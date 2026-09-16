from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin


class ImportBatch(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "import_batches"

    payload_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    source_dataset: Mapped[str] = mapped_column(String(64))
    source_version: Mapped[str] = mapped_column(String(64))
    source_kind: Mapped[str] = mapped_column(String(32))
    adapter_version: Mapped[str] = mapped_column(String(64))
    counts: Mapped[dict[str, int]] = mapped_column(JSON)


class ImportedRecord(IdMixin, CreatedAtMixin, Base):
    """Immutable source snapshot; id is also the deterministic domain entity id."""

    __tablename__ = "imported_records"

    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
