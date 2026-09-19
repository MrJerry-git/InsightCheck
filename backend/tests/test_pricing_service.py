from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ExamItem, ExamItemPriceRecord
from app.models.enums import CostLevel
from app.schemas.plan_builder import PlanBuildRequest, PlanCandidate
from app.services.plan_builder import build_plan, to_snapshot
from app.services.pricing import ExamItemPrice
from app.services.pricing_service import (
    EMPTY_CATALOG_VERSION,
    load_price_catalog,
    seed_demo_prices,
)

AS_OF = date(2025, 12, 31)


def make_item(db: Session, code: str, level: CostLevel, radiation: bool = False) -> ExamItem:
    item = ExamItem(
        code=code,
        name=f"{code} 项目",
        category="影像检查" if radiation else "实验室检查",
        radiation=radiation,
        cost_level=level,
    )
    db.add(item)
    db.commit()
    return item


def add_price(db: Session, item: ExamItem, **kwargs) -> ExamItemPriceRecord:
    payload = {
        "amount_cents": 10_000,
        "currency": "CNY",
        "source": "演示价",
        "effective_from": date(2024, 1, 1),
        "is_demo_price": True,
        **kwargs,
    }
    record = ExamItemPriceRecord(exam_item_id=item.id, **payload)
    db.add(record)
    db.commit()
    return record


def test_seed_demo_prices_is_idempotent(db_session: Session):
    make_item(db_session, "CHEST_CT", CostLevel.HIGH, radiation=True)
    make_item(db_session, "LIVER_FUNCTION_PANEL", CostLevel.LOW)

    assert seed_demo_prices(db_session) == 2
    assert seed_demo_prices(db_session) == 0
    demo_record = db_session.scalar(
        select(ExamItemPriceRecord).where(ExamItemPriceRecord.is_demo_price)
    )
    assert demo_record is not None

    catalog = load_price_catalog(db_session, as_of_date=AS_OF)
    assert catalog.catalog_version.startswith("db-price-catalog-")
    assert {price.exam_item_code for price in catalog.prices} == {
        "CHEST_CT",
        "LIVER_FUNCTION_PANEL",
    }
    assert catalog.has_demo_price() is True
    chest = catalog.lookup("CHEST_CT", AS_OF)
    assert chest is not None
    assert chest.amount_cents == 128_000


def test_load_price_catalog_respects_effective_range_and_institution(db_session: Session):
    item = make_item(db_session, "CHEST_CT", CostLevel.HIGH, radiation=True)
    add_price(db_session, item, amount_cents=100_000, source="演示通用价")
    add_price(
        db_session,
        item,
        amount_cents=150_000,
        source="演示机构价",
        institution="演示医院",
        effective_from=date(2024, 6, 1),
    )
    add_price(
        db_session,
        item,
        amount_cents=1,
        source="演示历史价",
        effective_from=date(2020, 1, 1),
        effective_to=date(2023, 12, 31),
    )

    general = load_price_catalog(db_session, as_of_date=AS_OF)
    general_codes = [price.source for price in general.prices]
    assert general_codes == ["演示通用价", "演示机构价"]
    assert general.lookup("CHEST_CT", AS_OF).amount_cents == 100_000

    scoped = load_price_catalog(db_session, as_of_date=AS_OF, institution="演示医院")
    assert scoped.lookup("CHEST_CT", AS_OF).amount_cents == 150_000

    historical = load_price_catalog(db_session, as_of_date=date(2022, 1, 1))
    assert historical.lookup("CHEST_CT", date(2022, 1, 1)).amount_cents == 1
    assert load_price_catalog(db_session, as_of_date=AS_OF).lookup("UNKNOWN", AS_OF) is None


def test_catalog_version_tracks_price_changes(db_session: Session):
    item = make_item(db_session, "LIVER_FUNCTION_PANEL", CostLevel.LOW)
    before = load_price_catalog(db_session, as_of_date=AS_OF)
    assert before.catalog_version == EMPTY_CATALOG_VERSION
    assert before.prices == ()

    add_price(db_session, item, amount_cents=12_000, source="演示价 A")
    first = load_price_catalog(db_session, as_of_date=AS_OF)
    add_price(
        db_session,
        item,
        amount_cents=13_000,
        source="演示价 B",
        effective_from=date(2025, 1, 1),
    )
    second = load_price_catalog(db_session, as_of_date=AS_OF)

    assert first.catalog_version != second.catalog_version
    assert first.catalog_version != EMPTY_CATALOG_VERSION
    assert first.lookup("LIVER_FUNCTION_PANEL", AS_OF).amount_cents == 12_000
    assert second.lookup("LIVER_FUNCTION_PANEL", AS_OF).amount_cents == 13_000


def test_catalog_version_covers_provenance_fields(db_session: Session):
    """来源、机构、地区、失效日期与演示标记变化时，目录版本也必须变化。"""

    item = make_item(db_session, "CHEST_CT", CostLevel.HIGH, radiation=True)
    record = add_price(
        db_session,
        item,
        amount_cents=128_000,
        source="演示价 A",
        institution="演示医院",
        region="演示地区",
        effective_to=date(2026, 12, 31),
    )
    version = load_price_catalog(db_session, as_of_date=AS_OF).catalog_version
    assert version.startswith("db-price-catalog-")

    def assert_version_changes(label: str) -> str:
        nonlocal version
        db_session.commit()
        current = load_price_catalog(db_session, as_of_date=AS_OF).catalog_version
        assert current != version, label
        version = current
        return current

    record.source = "演示价 B"
    assert_version_changes("source")
    record.institution = "另一家医院"
    assert_version_changes("institution")
    record.region = "另一地区"
    assert_version_changes("region")
    record.effective_to = date(2026, 6, 30)
    assert_version_changes("effective_to")
    record.source_url = "https://example.invalid/catalog"
    assert_version_changes("source_url")
    record.is_demo_price = False
    assert_version_changes("is_demo_price")
    record.note = "补充说明"
    assert_version_changes("note")


def test_source_url_must_be_non_blank_http_address():
    for invalid in ("   ", "example.invalid/catalog", "ftp://example.invalid/catalog", "https://"):
        with pytest.raises(ValidationError):
            ExamItemPrice(
                exam_item_code="CHEST_CT",
                amount_cents=128_000,
                currency="CNY",
                source="某机构价目表",
                source_url=invalid,
                effective_from=date(2024, 1, 1),
                is_demo_price=False,
            )
    cleaned = ExamItemPrice(
        exam_item_code="CHEST_CT",
        amount_cents=128_000,
        currency="CNY",
        source="  某机构价目表  ",
        source_url="  https://example.invalid/catalog  ",
        institution="   ",
        effective_from=date(2024, 1, 1),
        is_demo_price=False,
    )
    assert cleaned.source == "某机构价目表"
    assert cleaned.source_url == "https://example.invalid/catalog"
    assert cleaned.institution is None
    with pytest.raises(ValidationError):
        ExamItemPrice(
            exam_item_code="CHEST_CT",
            amount_cents=128_000,
            currency="CNY",
            source="   ",
            effective_from=date(2024, 1, 1),
        )


def test_database_rejects_blank_source_and_invalid_url(db_session: Session):
    item = make_item(db_session, "CHEST_CT", CostLevel.HIGH, radiation=True)
    for kwargs in (
        {"source": "   ", "source_url": None, "is_demo_price": True},
        {"source": "某机构价目表", "source_url": "   ", "is_demo_price": False},
        {
            "source": "某机构价目表",
            "source_url": "example.invalid/catalog",
            "is_demo_price": False,
        },
    ):
        db_session.add(
            ExamItemPriceRecord(
                exam_item_id=item.id,
                amount_cents=128_000,
                currency="CNY",
                effective_from=date(2024, 1, 1),
                **kwargs,
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()


def test_real_price_requires_source_url_in_database(db_session: Session):
    item = make_item(db_session, "CHEST_CT", CostLevel.HIGH, radiation=True)
    db_session.add(
        ExamItemPriceRecord(
            exam_item_id=item.id,
            amount_cents=128_000,
            currency="CNY",
            source="口头询价",
            source_url=None,
            effective_from=date(2024, 1, 1),
            is_demo_price=False,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    add_price(
        db_session,
        item,
        amount_cents=128_000,
        source="某机构价目表",
        source_url="https://example.invalid/catalog",
        is_demo_price=False,
    )
    catalog = load_price_catalog(db_session, as_of_date=AS_OF)
    assert catalog.prices[0].is_demo_price is False
    assert catalog.prices[0].source_url is not None


def test_plan_builder_consumes_database_price_catalog(db_session: Session):
    chest = make_item(db_session, "CHEST_CT", CostLevel.HIGH, radiation=True)
    liver = make_item(db_session, "LIVER_FUNCTION_PANEL", CostLevel.LOW)
    seed_demo_prices(db_session)
    catalog = load_price_catalog(db_session, as_of_date=AS_OF)

    request = PlanBuildRequest(
        trace_id="trace-db",
        patient_id="patient-1",
        as_of_date=AS_OF,
        candidates=(
            PlanCandidate(
                exam_item_id=chest.id,
                code="CHEST_CT",
                name="胸部 CT 项目",
                category="影像检查",
                radiation=True,
                cost_level=CostLevel.HIGH,
                score=0.9,
            ),
            PlanCandidate(
                exam_item_id=liver.id,
                code="LIVER_FUNCTION_PANEL",
                name="肝功能组合 项目",
                category="实验室检查",
                cost_level=CostLevel.LOW,
                score=0.8,
            ),
        ),
        price_catalog=catalog,
    )
    result = build_plan(request)
    simplified = next(plan for plan in result.tiers if plan.tier.value == "simplified")
    deep = next(plan for plan in result.tiers if plan.tier.value == "deep")

    assert simplified.cost_summary.known_total_cents == 12_000
    assert simplified.cost_summary.includes_demo_price is True
    assert deep.cost_summary.known_total_cents == 140_000
    assert result.price_catalog_version == catalog.catalog_version

    snapshot = to_snapshot(result)
    assert snapshot["tier_mode"] == "single_request_all_tiers"
    assert snapshot["adopted_tier"] == "standard"
    assert len(snapshot["tiers"]) == 3
    assert snapshot["adopted_plan"]["tier"] == "standard"
    assert snapshot["adopted_plan"]["items"]
