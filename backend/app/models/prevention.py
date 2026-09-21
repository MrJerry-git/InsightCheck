from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin


class PreventionReport(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "prevention_reports"
    label: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
