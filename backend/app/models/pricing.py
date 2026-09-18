"""体检验项目录的价格记录：金额使用整数分，保留来源、适用范围和演示价标记。

与 ``app.services.pricing.ExamItemPrice``（纯计算使用的价格模型）区分：
本模型是持久化记录，字段语义一致，便于把数据库内容加载成价格目录。
"""

from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin


class ExamItemPriceRecord(IdMixin, CreatedAtMixin, Base):
    """单个体检项目的一条价格记录，可带机构或地区限定与生效区间。"""

    __tablename__ = "exam_item_prices"
    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="amount_cents_non_negative"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="effective_range_order",
        ),
        CheckConstraint(
            "is_demo_price OR source_url IS NOT NULL",
            name="real_price_requires_source_url",
        ),
        CheckConstraint("trim(source) <> ''", name="source_not_blank"),
        CheckConstraint(
            "source_url IS NULL OR trim(source_url) <> ''",
            name="source_url_not_blank",
        ),
        CheckConstraint(
            "source_url IS NULL OR source_url LIKE 'http://%' OR source_url LIKE 'https://%'",
            name="source_url_scheme",
        ),
        Index("ix_exam_item_prices_effective_from", "effective_from"),
    )

    exam_item_id: Mapped[str] = mapped_column(
        ForeignKey("exam_items.id", ondelete="CASCADE"), index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", server_default="CNY")
    source: Mapped[str] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    institution: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_demo_price: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
