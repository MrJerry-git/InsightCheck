"""价格目录的持久化读写：把数据库记录加载为纯计算使用的 ``PriceCatalog``。

读取只按截止日期与适用范围筛选，不做任何金额计算；金额保持整数分。
"""

from collections.abc import Sequence
from datetime import date
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExamItem, ExamItemPriceRecord
from app.services.pricing import (
    DEFAULT_CURRENCY,
    DEMO_EFFECTIVE_FROM,
    DEMO_PRICE_CENTS_BY_COST_LEVEL,
    DEMO_PRICE_SOURCE,
    ExamItemPrice,
    PriceCatalog,
)

EMPTY_CATALOG_VERSION = "db-price-catalog-empty"


def load_price_catalog(
    db: Session,
    *,
    as_of_date: date,
    institution: str | None = None,
    region: str | None = None,
    currency: str | None = None,
) -> PriceCatalog:
    """加载在 ``as_of_date`` 生效的价格，机构或地区为空的记录视为通用价格。"""

    statement = (
        select(ExamItemPriceRecord, ExamItem.code)
        .join(ExamItem, ExamItem.id == ExamItemPriceRecord.exam_item_id)
        .where(ExamItemPriceRecord.effective_from <= as_of_date)
        .where(
            ExamItemPriceRecord.effective_to.is_(None)
            | (ExamItemPriceRecord.effective_to >= as_of_date)
        )
    )
    if institution is not None:
        statement = statement.where(
            ExamItemPriceRecord.institution.is_(None)
            | (ExamItemPriceRecord.institution == institution)
        )
    if region is not None:
        statement = statement.where(
            ExamItemPriceRecord.region.is_(None) | (ExamItemPriceRecord.region == region)
        )
    if currency is not None:
        statement = statement.where(ExamItemPriceRecord.currency == currency.strip().upper())
    rows = db.execute(
        statement.order_by(
            ExamItem.code,
            ExamItemPriceRecord.effective_from,
            ExamItemPriceRecord.id,
        )
    ).all()
    prices = tuple(
        ExamItemPrice(
            exam_item_code=code,
            amount_cents=record.amount_cents,
            currency=record.currency,
            source=record.source,
            source_url=record.source_url,
            institution=record.institution,
            region=record.region,
            effective_from=record.effective_from,
            effective_to=record.effective_to,
            is_demo_price=record.is_demo_price,
            note=record.note,
        )
        for record, code in rows
    )
    return PriceCatalog(
        catalog_version=catalog_version(rows),
        prices=prices,
        institution=institution,
        region=region,
    )


def catalog_version(rows: Sequence[tuple[ExamItemPriceRecord, str]]) -> str:
    """用价格内容生成目录版本，价格变化时快照版本随之变化。"""

    if not rows:
        return EMPTY_CATALOG_VERSION
    identity = "|".join(
        sorted(
            f"{record.id}:{code}:{record.amount_cents}:{record.currency}:{record.effective_from}"
            for record, code in rows
        )
    )
    return f"db-price-catalog-{sha256(identity.encode('utf-8')).hexdigest()[:12]}"


def seed_demo_prices(
    db: Session,
    *,
    effective_from: date = DEMO_EFFECTIVE_FROM,
    currency: str = DEFAULT_CURRENCY,
) -> int:
    """为目录中尚无价格的项目补一条演示价，可重复执行，返回新增条数。

    只写入 ``is_demo_price=True`` 的记录，真实价格必须由人工按来源录入。
    """

    items = db.scalars(select(ExamItem).order_by(ExamItem.code)).all()
    priced = {record.exam_item_id for record in db.scalars(select(ExamItemPriceRecord)).all()}
    added = 0
    try:
        for item in items:
            if item.id in priced:
                continue
            level = item.cost_level.value
            amount_cents = DEMO_PRICE_CENTS_BY_COST_LEVEL.get(level)
            if amount_cents is None:
                continue
            db.add(
                ExamItemPriceRecord(
                    exam_item_id=item.id,
                    amount_cents=amount_cents,
                    currency=currency,
                    source=DEMO_PRICE_SOURCE,
                    source_url=None,
                    institution=None,
                    region=None,
                    effective_from=effective_from,
                    is_demo_price=True,
                    note=f"费用等级 {level}",
                )
            )
            added += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return added
