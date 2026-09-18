import json
from datetime import date

import pytest
from pydantic import ValidationError

from app.models.enums import CostLevel, PlanTier
from app.rules.models import FinalRuleStatus, RuleEvaluationResult
from app.schemas.plan_builder import (
    BudgetSpec,
    BudgetStatus,
    CandidateRuleStatus,
    ConflictCode,
    CostStatus,
    ExclusionReason,
    PlanBuildRequest,
    PlanCandidate,
)
from app.services.plan_builder import PlanBuilder, build_plan, to_snapshot
from app.services.pricing import ExamItemPrice, PriceCatalog, build_demo_catalog, format_amount

AS_OF = date(2025, 12, 31)

CATALOG = build_demo_catalog(
    [
        ("CHEST_CT", "high"),
        ("LIVER_FUNCTION_PANEL", "low"),
        ("THYROID_US", "medium"),
        ("CARDIAC_MRI", "high"),
        ("BONE_DENSITY", "medium"),
        ("LUNG_XRAY", "low"),
        ("STOOL_TEST", "low"),
    ]
)


def candidate(
    code: str,
    *,
    score: float,
    cost_level: CostLevel,
    radiation: bool = False,
    rule_status: CandidateRuleStatus = CandidateRuleStatus.NOT_CONFIGURED,
    rule_notes: tuple[str, ...] = (),
    exam_item_id: str | None = None,
) -> PlanCandidate:
    return PlanCandidate(
        exam_item_id=exam_item_id or f"id-{code}",
        code=code,
        name=f"{code} 项目",
        category="影像检查" if radiation else "实验室检查",
        radiation=radiation,
        cost_level=cost_level,
        score=score,
        rule_status=rule_status,
        rule_notes=rule_notes,
        rule_set_version="sha256:test",
    )


def default_candidates() -> list[PlanCandidate]:
    return [
        candidate("CHEST_CT", score=0.90, cost_level=CostLevel.HIGH, radiation=True),
        candidate("LIVER_FUNCTION_PANEL", score=0.80, cost_level=CostLevel.LOW),
        candidate("THYROID_US", score=0.70, cost_level=CostLevel.MEDIUM),
        candidate("CARDIAC_MRI", score=0.65, cost_level=CostLevel.HIGH),
        candidate("BONE_DENSITY", score=0.60, cost_level=CostLevel.MEDIUM),
        candidate("LUNG_XRAY", score=0.50, cost_level=CostLevel.LOW, radiation=True),
        candidate("STOOL_TEST", score=0.40, cost_level=CostLevel.LOW),
    ]


def request_for(
    candidates: list[PlanCandidate],
    *,
    budget: BudgetSpec | None = None,
    catalog: PriceCatalog = CATALOG,
) -> PlanBuildRequest:
    return PlanBuildRequest(
        trace_id="trace-1",
        patient_id="patient-1",
        as_of_date=AS_OF,
        candidates=tuple(candidates),
        price_catalog=catalog,
        budget=budget,
    )


def tier(result, tier: PlanTier):
    return next(plan for plan in result.tiers if plan.tier is tier)


def item_ids(plan) -> set[str]:
    return {item.exam_item_id for item in plan.items}


def codes(plan) -> list[str]:
    return [item.code for item in plan.items]


def test_same_input_same_output_and_order_independent():
    shuffled = list(reversed(default_candidates()))
    first = build_plan(request_for(default_candidates()))
    second = build_plan(request_for(default_candidates()))
    third = build_plan(request_for(shuffled))

    assert first.model_dump() == second.model_dump()
    assert first.model_dump(mode="json") == third.model_dump(mode="json")
    assert first.strategy_version == "plan-builder-v1"
    assert [plan.tier for plan in first.tiers] == [
        PlanTier.SIMPLIFIED,
        PlanTier.STANDARD,
        PlanTier.DEEP,
    ]


def test_tier_sets_are_nested_and_deep_allows_radiation():
    result = build_plan(request_for(default_candidates()))
    simplified, standard, deep = (tier(result, t) for t in PlanTier)

    assert item_ids(simplified) <= item_ids(standard) <= item_ids(deep)
    assert codes(simplified) == [
        "LIVER_FUNCTION_PANEL",
        "THYROID_US",
        "BONE_DENSITY",
        "STOOL_TEST",
    ]
    assert "CARDIAC_MRI" in codes(standard)
    assert "CHEST_CT" not in codes(standard)
    assert "CHEST_CT" in codes(deep)
    assert all(item.rank == index for index, item in enumerate(deep.items, 1))


def test_blocked_item_never_returns_in_higher_tier():
    candidates = default_candidates()
    candidates[0] = candidate(
        "CHEST_CT",
        score=1.0,
        cost_level=CostLevel.HIGH,
        radiation=True,
        rule_status=CandidateRuleStatus.BLOCKED,
        rule_notes=("规则 BLOCK：项目不适用",),
    )
    result = build_plan(request_for(candidates))

    for plan in result.tiers:
        assert "CHEST_CT" not in codes(plan)
        blocked = [entry for entry in plan.excluded if entry.code == "CHEST_CT"]
        assert blocked
        assert blocked[0].reason_code is ExclusionReason.RULE_BLOCKED
        assert "规则 BLOCK" in blocked[0].reason


def test_deferred_item_never_returns_in_higher_tier():
    candidates = [
        candidate(
            "LUNG_XRAY",
            score=1.0,
            cost_level=CostLevel.LOW,
            radiation=True,
            rule_status=CandidateRuleStatus.DEFERRED,
        ),
        candidate("LIVER_FUNCTION_PANEL", score=0.5, cost_level=CostLevel.LOW),
    ]
    result = build_plan(request_for(candidates))
    deep = tier(result, PlanTier.DEEP)

    assert "LUNG_XRAY" not in codes(deep)
    assert deep.excluded[0].reason_code is ExclusionReason.RULE_DEFERRED


def test_review_items_survive_budget_conflict():
    candidates = [
        candidate(
            "STOOL_TEST",
            score=0.40,
            cost_level=CostLevel.LOW,
            rule_status=CandidateRuleStatus.REVIEW_REQUIRED,
            rule_notes=("规则要求人工复核",),
        ),
        *[c for c in default_candidates() if c.code != "STOOL_TEST"],
    ]
    budget = BudgetSpec(limit_cents=10_000, currency="CNY")
    result = build_plan(request_for(candidates, budget=budget))
    simplified = tier(result, PlanTier.SIMPLIFIED)

    assert "STOOL_TEST" in codes(simplified)
    assert simplified.budget_status is BudgetStatus.OVER_BUDGET
    assert ConflictCode.BUDGET_EXCEEDED in {c.code for c in simplified.conflicts}
    assert any(entry.reason_code is ExclusionReason.BUDGET_LIMIT for entry in simplified.excluded)
    assert "应复核项目未被删除" in simplified.budget_note


def test_review_items_beyond_tier_limit_are_kept_and_reported():
    candidates = [
        candidate(
            f"ITEM_{index}",
            score=0.5 + index / 100,
            cost_level=CostLevel.LOW,
            rule_status=CandidateRuleStatus.REVIEW_REQUIRED,
        )
        for index in range(5)
    ]
    result = build_plan(request_for(candidates))
    simplified = tier(result, PlanTier.SIMPLIFIED)

    assert len(simplified.items) == 5
    assert ConflictCode.REVIEW_ITEMS_EXCEED_TIER_SIZE in {c.code for c in simplified.conflicts}
    assert "应复核项目优先保留" in simplified.conflicts[0].message


def test_unknown_price_blocks_total_claim():
    catalog = PriceCatalog(
        catalog_version="partial-v1",
        prices=(CATALOG.lookup("LIVER_FUNCTION_PANEL", AS_OF),),
    )
    result = build_plan(
        request_for(default_candidates(), budget=BudgetSpec(limit_cents=100_000), catalog=catalog)
    )
    standard = tier(result, PlanTier.STANDARD)

    assert standard.cost_summary.is_complete is False
    assert standard.cost_summary.unpriced_item_count == len(standard.items) - 1
    assert standard.cost_summary.currency == "CNY"
    assert standard.budget_status is BudgetStatus.UNKNOWN_PRICES
    assert ConflictCode.UNKNOWN_PRICE_BLOCKS_TOTAL in {c.code for c in standard.conflicts}
    assert "不能据此声称总价完整" in standard.cost_summary.disclosure
    assert "无法保证不超预算" in standard.budget_note
    assert any(item.cost_status is CostStatus.UNPRICED for item in standard.items)


def test_mixed_currency_is_not_summed():
    usd = ExamItemPrice(
        exam_item_code="THYROID_US",
        amount_cents=9_900,
        currency="usd",
        source="测试用外部价格",
        source_url="https://example.invalid/price",
        effective_from=date(2024, 1, 1),
        is_demo_price=False,
    )
    catalog = PriceCatalog(
        catalog_version="mixed-v1",
        prices=tuple(CATALOG.prices) + (usd,),
    )
    result = build_plan(
        request_for(default_candidates(), budget=BudgetSpec(limit_cents=1_000_000), catalog=catalog)
    )
    standard = tier(result, PlanTier.STANDARD)

    assert usd.currency == "USD"
    assert standard.cost_summary.mixed_currency is True
    assert standard.cost_summary.known_total_cents is None
    assert standard.cost_summary.currency is None
    assert set(standard.cost_summary.per_currency_totals) == {"CNY", "USD"}
    assert standard.budget_status is BudgetStatus.UNDETERMINED
    assert ConflictCode.MIXED_CURRENCY in {c.code for c in standard.conflicts}


def test_empty_catalog_and_all_blocked_are_explained():
    empty = build_plan(request_for([]))
    assert all(plan.items == () for plan in empty.tiers)
    assert any("候选目录为空" in note for note in empty.notes)
    assert empty.notes

    blocked = [
        candidate(
            "CHEST_CT",
            score=0.9,
            cost_level=CostLevel.HIGH,
            radiation=True,
            rule_status=CandidateRuleStatus.BLOCKED,
        ),
        candidate(
            "LIVER_FUNCTION_PANEL",
            score=0.8,
            cost_level=CostLevel.LOW,
            rule_status=CandidateRuleStatus.DEFERRED,
        ),
    ]
    result = build_plan(request_for(blocked))
    for plan in result.tiers:
        assert plan.items == ()
        assert len(plan.excluded) == 2
        assert plan.cost_summary.known_total_cents == 0
    assert any("规则禁止或要求暂缓" in note for note in result.notes)


def test_duplicate_candidates_are_deduplicated():
    candidates = [
        candidate("LIVER_FUNCTION_PANEL", score=0.2, cost_level=CostLevel.LOW),
        candidate("LIVER_FUNCTION_PANEL", score=0.9, cost_level=CostLevel.LOW),
    ]
    result = build_plan(request_for(candidates))
    standard = tier(result, PlanTier.STANDARD)

    assert codes(standard) == ["LIVER_FUNCTION_PANEL"]
    assert standard.items[0].score == 0.9
    assert standard.excluded[0].reason_code is ExclusionReason.DUPLICATE_CANDIDATE
    assert any("重复候选" in note for note in result.notes)


def test_price_change_does_not_alter_saved_snapshot():
    old = build_plan(request_for(default_candidates()))
    new_price = ExamItemPrice(
        exam_item_code="CARDIAC_MRI",
        amount_cents=999_900,
        currency="CNY",
        source="DEMO PRICE：调价演练",
        effective_from=date(2024, 1, 1),
        is_demo_price=True,
    )
    updated_catalog = PriceCatalog(
        catalog_version="demo-price-catalog-v2",
        prices=tuple(p for p in CATALOG.prices if p.exam_item_code != "CARDIAC_MRI") + (new_price,),
    )
    new = build_plan(request_for(default_candidates(), catalog=updated_catalog))

    def price_of(result, code: str) -> int | None:
        for plan in result.tiers:
            for item in plan.items:
                if item.code == code:
                    return item.price.amount_cents
        return None

    assert price_of(old, "CARDIAC_MRI") == 128_000
    assert price_of(new, "CARDIAC_MRI") == 999_900
    assert old.model_dump(mode="json") != new.model_dump(mode="json")
    assert old.price_catalog_version == "demo-price-catalog-v1"
    assert new.price_catalog_version == "demo-price-catalog-v2"


def test_demo_prices_are_labelled_and_serializable():
    result = build_plan(request_for(default_candidates()))
    standard = tier(result, PlanTier.STANDARD)
    payload = json.loads(result.model_dump_json())

    assert standard.cost_summary.includes_demo_price is True
    assert "演示价" in standard.cost_summary.disclosure
    assert all(item.price.is_demo_price for item in standard.items)
    assert all(item.price.source for item in standard.items)
    assert payload["schema_version"] == "plan-builder-contract-v1"
    assert len(payload["tiers"]) == 3
    assert payload["disclosures"]


def test_real_price_requires_verifiable_source():
    with pytest.raises(ValidationError):
        ExamItemPrice(
            exam_item_code="CHEST_CT",
            amount_cents=128_000,
            currency="CNY",
            source="口头询价",
            effective_from=date(2024, 1, 1),
            is_demo_price=False,
        )
    priced = ExamItemPrice(
        exam_item_code="CHEST_CT",
        amount_cents=128_000,
        currency="CNY",
        source="某机构 2024 年价目表",
        source_url="https://example.invalid/catalog",
        effective_from=date(2024, 1, 1),
        is_demo_price=False,
    )
    assert priced.source_url is not None
    assert priced.currency == "CNY"


def test_lookup_prefers_specific_and_effective_price():
    generic = ExamItemPrice(
        exam_item_code="CHEST_CT",
        amount_cents=100_000,
        currency="CNY",
        source="演示通用价",
        effective_from=date(2024, 1, 1),
    )
    specific = ExamItemPrice(
        exam_item_code="CHEST_CT",
        amount_cents=150_000,
        currency="CNY",
        source="演示机构价",
        institution="演示医院",
        effective_from=date(2024, 6, 1),
    )
    expired = ExamItemPrice(
        exam_item_code="CHEST_CT",
        amount_cents=1,
        currency="CNY",
        source="演示历史价",
        effective_from=date(2020, 1, 1),
        effective_to=date(2023, 12, 31),
    )
    catalog = PriceCatalog(catalog_version="lookup-v1", prices=(generic, specific, expired))

    assert catalog.lookup("chest_ct", AS_OF).amount_cents == 100_000
    assert catalog.lookup("CHEST_CT", AS_OF, institution="演示医院").amount_cents == 150_000
    assert catalog.lookup("CHEST_CT", date(2022, 1, 1)).amount_cents == 1
    assert catalog.lookup("UNKNOWN_ITEM", AS_OF) is None


def test_budget_status_without_prices_or_budget():
    no_budget = tier(build_plan(request_for(default_candidates())), PlanTier.STANDARD)
    assert no_budget.budget_status is BudgetStatus.NOT_PROVIDED
    assert "未提供预算偏好" in no_budget.budget_note

    empty_catalog = PriceCatalog(catalog_version="empty-v1")
    result = build_plan(
        request_for(
            default_candidates(),
            budget=BudgetSpec(limit_cents=100_000, currency="CNY"),
            catalog=empty_catalog,
        )
    )
    standard = tier(result, PlanTier.STANDARD)
    assert standard.cost_summary.priced_item_count == 0
    assert standard.cost_summary.unpriced_item_codes
    assert standard.budget_status is BudgetStatus.UNKNOWN_PRICES
    assert any("未提供价格目录" in note for note in result.notes)


def test_identical_tiers_are_reported_with_reason():
    candidates = [
        candidate("LIVER_FUNCTION_PANEL", score=0.8, cost_level=CostLevel.LOW),
        candidate("CHEST_CT", score=0.9, cost_level=CostLevel.HIGH, radiation=True),
    ]
    result = build_plan(request_for(candidates))
    simplified, standard = tier(result, PlanTier.SIMPLIFIED), tier(result, PlanTier.STANDARD)

    assert item_ids(simplified) == item_ids(standard)
    assert PlanTier.STANDARD in simplified.identical_to
    assert ConflictCode.TIERS_NOT_DISTINCT in {c.code for c in simplified.conflicts}
    assert "项目集合相同" in simplified.selection_note


def test_plan_builder_can_consume_rule_engine_output():
    empty_trace = RuleEvaluationResult(
        trace_id="trace-1",
        deepfm_score=0.5,
        adjusted_score=0.5,
        final_status=FinalRuleStatus.ALLOWED,
        rule_decisions=[],
        execution_trace=[],
        rule_set_version="sha256:none",
    )
    assert (
        CandidateRuleStatus.from_rule_evaluation(empty_trace) is CandidateRuleStatus.NOT_CONFIGURED
    )
    assert (
        CandidateRuleStatus.from_final_status(FinalRuleStatus.BLOCKED)
        is CandidateRuleStatus.BLOCKED
    )


def test_builder_is_pure_and_reusable():
    builder = PlanBuilder()
    request = request_for(default_candidates())
    assert builder.build(request).model_dump() == builder.build(request).model_dump()


def test_format_amount_uses_integer_cents():
    assert format_amount(12_000, "CNY") == "120.00 CNY"
    assert format_amount(5, "CNY") == "0.05 CNY"
    assert format_amount(999_900, "USD") == "9999.00 USD"


def test_duplicate_with_conflicting_rule_status_keeps_blocked():
    """低分记录被禁止、高分记录被允许时，禁止结论不能被分数覆盖。"""

    candidates = [
        candidate(
            "LIVER_FUNCTION_PANEL",
            score=0.20,
            cost_level=CostLevel.LOW,
            rule_status=CandidateRuleStatus.BLOCKED,
            rule_notes=("规则 BLOCK：该项目不适用",),
            exam_item_id="item-liver",
        ),
        candidate(
            "LIVER_FUNCTION_PANEL",
            score=0.90,
            cost_level=CostLevel.LOW,
            rule_status=CandidateRuleStatus.ALLOWED,
            exam_item_id="item-liver",
        ),
        candidate("THYROID_US", score=0.50, cost_level=CostLevel.MEDIUM),
    ]
    result = build_plan(request_for(candidates))
    standard = tier(result, PlanTier.STANDARD)
    deep = tier(result, PlanTier.DEEP)

    assert "LIVER_FUNCTION_PANEL" not in codes(standard)
    assert "LIVER_FUNCTION_PANEL" not in codes(deep)
    assert "THYROID_US" in codes(standard)
    reasons = {
        entry.reason_code for entry in standard.excluded if entry.code == "LIVER_FUNCTION_PANEL"
    }
    assert ExclusionReason.RULE_BLOCKED in reasons
    assert ExclusionReason.DUPLICATE_CANDIDATE in reasons
    assert ConflictCode.DUPLICATE_RULE_STATUS_CONFLICT in {c.code for c in standard.conflicts}
    assert any("最严格" in note for note in result.notes)


def test_duplicate_deferred_beats_higher_score_allowed():
    candidates = [
        candidate(
            "LUNG_XRAY",
            score=0.30,
            cost_level=CostLevel.LOW,
            radiation=True,
            rule_status=CandidateRuleStatus.DEFERRED,
            exam_item_id="item-lung",
        ),
        candidate(
            "LUNG_XRAY",
            score=0.95,
            cost_level=CostLevel.LOW,
            radiation=True,
            rule_status=CandidateRuleStatus.NOT_CONFIGURED,
            exam_item_id="item-lung",
        ),
    ]
    result = build_plan(request_for(candidates))

    for plan in result.tiers:
        assert "LUNG_XRAY" not in codes(plan)
        reasons = {entry.reason_code for entry in plan.excluded}
        assert ExclusionReason.RULE_DEFERRED in reasons


def test_duplicate_merge_keeps_all_rule_evidence():
    candidates = [
        candidate(
            "THYROID_US",
            score=0.40,
            cost_level=CostLevel.MEDIUM,
            rule_notes=("记录 A：建议复核",),
            exam_item_id="item-thyroid",
        ).model_copy(update={"rule_evidence_refs": ("ev-a",)}),
        candidate(
            "THYROID_US",
            score=0.80,
            cost_level=CostLevel.MEDIUM,
            rule_notes=("记录 B：缺随访",),
            exam_item_id="item-thyroid",
        ).model_copy(
            update={"rule_evidence_refs": ("ev-b",), "rule_set_version": "sha256:rules-2"}
        ),
    ]
    result = build_plan(request_for(candidates))
    standard = tier(result, PlanTier.STANDARD)
    selected = next(item for item in standard.items if item.code == "THYROID_US")

    assert selected.score == 0.80
    assert set(selected.rule_notes) == {"记录 A：建议复核", "记录 B：缺随访"}
    assert set(selected.rule_evidence_refs) == {"ev-a", "ev-b"}


def test_cross_currency_budget_filter_does_not_mix_currencies():
    """预算筛选必须按币种分别累计，不能把人民币金额加进美元预算比较。"""

    catalog = PriceCatalog(
        catalog_version="mixed-budget-v1",
        prices=(
            ExamItemPrice(
                exam_item_code="CHEST_CT",
                amount_cents=128_000,
                currency="CNY",
                source="演示价",
                effective_from=date(2024, 1, 1),
            ),
            ExamItemPrice(
                exam_item_code="THYROID_US",
                amount_cents=40_000,
                currency="USD",
                source="演示价",
                effective_from=date(2024, 1, 1),
            ),
        ),
    )
    candidates = [
        candidate("CHEST_CT", score=0.90, cost_level=CostLevel.LOW),
        candidate("THYROID_US", score=0.80, cost_level=CostLevel.LOW),
    ]
    result = build_plan(
        request_for(
            candidates,
            budget=BudgetSpec(limit_cents=50_000, currency="USD"),
            catalog=catalog,
        )
    )
    standard = tier(result, PlanTier.STANDARD)

    assert "THYROID_US" in codes(standard)
    assert not any(
        entry.code == "THYROID_US" and entry.reason_code is ExclusionReason.BUDGET_LIMIT
        for entry in standard.excluded
    )
    assert standard.cost_summary.per_currency_totals == {"CNY": 128_000, "USD": 40_000}
    assert standard.budget_status is BudgetStatus.UNDETERMINED
    assert "总预算不可判定" in standard.budget_note
    assert ConflictCode.MIXED_CURRENCY in {c.code for c in standard.conflicts}


def test_tiers_stay_nested_under_budget_pressure():
    """高档不能因为预算被低档已选项目挤掉：基础档 ⊆ 标准档 ⊆ 深入档。"""

    candidates = [
        candidate("CHEST_CT", score=0.90, cost_level=CostLevel.HIGH, radiation=True),
        candidate("LIVER_FUNCTION_PANEL", score=0.80, cost_level=CostLevel.LOW),
        candidate("THYROID_US", score=0.70, cost_level=CostLevel.MEDIUM),
        candidate("BONE_DENSITY", score=0.60, cost_level=CostLevel.MEDIUM),
        candidate("STOOL_TEST", score=0.40, cost_level=CostLevel.LOW),
    ]
    result = build_plan(
        request_for(candidates, budget=BudgetSpec(limit_cents=130_000, currency="CNY"))
    )
    simplified, standard, deep = (tier(result, t) for t in PlanTier)

    assert item_ids(simplified) <= item_ids(standard) <= item_ids(deep)
    assert item_ids(simplified) == item_ids(deep)
    assert "CHEST_CT" not in codes(deep)
    assert any(
        entry.code == "CHEST_CT" and entry.reason_code is ExclusionReason.BUDGET_LIMIT
        for entry in deep.excluded
    )
    assert "承自低档结果" in deep.selection_note


def test_inherited_items_record_origin_tier():
    result = build_plan(request_for(default_candidates()))
    simplified, standard, deep = (tier(result, t) for t in PlanTier)
    simplified_ids = item_ids(simplified)
    standard_ids = item_ids(standard)

    assert all(item.inherited_from is None for item in simplified.items)
    assert all(
        item.inherited_from is PlanTier.SIMPLIFIED
        for item in standard.items
        if item.exam_item_id in simplified_ids
    )
    origins = {item.inherited_from for item in deep.items}
    assert origins == {None, PlanTier.SIMPLIFIED, PlanTier.STANDARD}
    assert all(
        item.inherited_from is PlanTier.STANDARD
        for item in deep.items
        if item.exam_item_id in standard_ids - simplified_ids
    )


def test_selected_items_keep_rule_evidence():
    candidates = [
        candidate(
            "STOOL_TEST",
            score=0.40,
            cost_level=CostLevel.LOW,
            rule_status=CandidateRuleStatus.REVIEW_REQUIRED,
            rule_notes=("规则要求人工复核：缺近期记录",),
        ).model_copy(
            update={
                "rule_evidence_refs": ("check-2025-06-22",),
                "rule_set_version": "sha256:rules-9",
            }
        )
    ]
    result = build_plan(request_for(candidates))
    deep = tier(result, PlanTier.DEEP)
    item = deep.items[0]

    assert item.requires_review is True
    assert item.rule_set_version == "sha256:rules-9"
    assert item.rule_notes == ("规则要求人工复核：缺近期记录",)
    assert item.rule_evidence_refs == ("check-2025-06-22",)
    assert result.rule_set_versions == ("sha256:rules-9",)
    snapshot = to_snapshot(result)
    deep_payload = next(plan for plan in snapshot["tiers"] if plan["tier"] == "deep")
    assert deep_payload["items"][0]["rule_evidence_refs"] == ["check-2025-06-22"]
