"""三档方案构建服务：把统一候选草稿扩展为基础、标准、深入三档。

设计约束（见 docs/TEAM_TASKS_V1.md 与 docs/PLAN_BUILDER_CONTRACT.md）：

* 纯服务：只做计算，不读写数据库、不训练模型、不调用规则引擎。
  规则结论由 ``app.rules`` 产出后作为输入传入，本模块只决定项目组合。
* 确定性：相同输入得到完全相同的输出，不依赖字典遍历顺序或当前时间。
* 档位只表达项目组合与预算偏好，不表达疾病风险或医学必要性。
* 三档逐档继承：基础档 ⊆ 标准档 ⊆ 深入档，高档在低档结果之上扩充，不会挤掉低档项目。
* 规则禁止（BLOCKED/DEFERRED）的项目在任何档位都不会因高分或预算被重新选入。
* 重复候选按保守策略合并：最严格的规则结论优先，模型分数不能覆盖禁止或暂缓。
* 规则要求复核的项目在所有档位保留；与预算冲突时返回冲突说明，不静默删除。
* 预算按币种分别累计，只与相同币种比较；无法换算时明确返回总预算不可判定。
* 价格与选取结果写入快照；之后调整价格目录不改变已保存的方案。
* 入选项目保留规则版本、说明与证据引用，保存后仍能解释“为什么需要复核”。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.models.enums import CostLevel, PlanTier
from app.schemas.plan_builder import (
    SCHEMA_VERSION,
    TIER_ORDER,
    BudgetSpec,
    BudgetStatus,
    CandidateRuleStatus,
    ConflictCode,
    CostStatus,
    CostSummary,
    ExcludedPlanItem,
    ExclusionReason,
    PlanBuildRequest,
    PlanBuildResult,
    PlanCandidate,
    PlanConflict,
    PriceSnapshot,
    SelectedPlanItem,
    TierPlan,
)
from app.services.pricing import ExamItemPrice, PriceCatalog, format_amount

STRATEGY_VERSION = "plan-builder-v1"
SNAPSHOT_TIER_MODE = "single_request_all_tiers"

DISCLOSURES: tuple[str, ...] = (
    "本结果是待复核的工程草稿，不代表医学必要性结论，也不能替代医生判断。",
    "档位只表达项目组合与预算偏好，不表达疾病风险高低。",
    "价格未知的项目不计入已知费用小计；含演示价时不能作为真实收费依据。",
)


@dataclass(frozen=True)
class TierPolicy:
    """单个档位的确定性选取策略。"""

    tier: PlanTier
    max_items: int
    allow_radiation: bool
    allowed_cost_levels: tuple[CostLevel, ...]
    description: str


TIER_POLICIES: dict[PlanTier, TierPolicy] = {
    PlanTier.SIMPLIFIED: TierPolicy(
        tier=PlanTier.SIMPLIFIED,
        max_items=4,
        allow_radiation=False,
        allowed_cost_levels=(CostLevel.LOW, CostLevel.MEDIUM),
        description="基础档：项目数最少，仅取低费用、无辐射项目",
    ),
    PlanTier.STANDARD: TierPolicy(
        tier=PlanTier.STANDARD,
        max_items=8,
        allow_radiation=False,
        allowed_cost_levels=(CostLevel.LOW, CostLevel.MEDIUM, CostLevel.HIGH),
        description="标准档：在基础档之上补充高费用项目，仍不含辐射项目",
    ),
    PlanTier.DEEP: TierPolicy(
        tier=PlanTier.DEEP,
        max_items=16,
        allow_radiation=True,
        allowed_cost_levels=(CostLevel.LOW, CostLevel.MEDIUM, CostLevel.HIGH),
        description="深入档：项目数最多，允许包含辐射项目",
    ),
}


class PlanBuilder:
    """无状态的三档方案构建器。"""

    def __init__(self, strategy_version: str = STRATEGY_VERSION) -> None:
        self._strategy_version = strategy_version

    def build(self, request: PlanBuildRequest) -> PlanBuildResult:
        tiers = tuple(tier for tier in TIER_ORDER if tier in request.tiers)
        strategy_version = request.strategy_version or self._strategy_version
        catalog = request.price_catalog
        kept, duplicates, duplicate_conflicts = _deduplicate(request.candidates)
        ordered = _order_candidates(kept)
        by_id = {item.exam_item_id: item for item in ordered}
        mandatory = [item for item in ordered if item.rule_status.requires_review]
        optional = [item for item in ordered if not item.rule_status.requires_review]
        forbidden = [item for item in ordered if item.rule_status.forbids_selection]
        selectable = [item for item in optional if not item.rule_status.forbids_selection]

        tier_plans: list[TierPlan] = []
        inherited_plan: TierPlan | None = None
        for tier in tiers:
            tier_plan = self._build_tier(
                tier=tier,
                mandatory=mandatory,
                selectable=selectable,
                forbidden=forbidden,
                duplicates=duplicates,
                duplicate_conflicts=duplicate_conflicts,
                inherited_plan=inherited_plan,
                by_id=by_id,
                catalog=catalog,
                request=request,
                strategy_version=strategy_version,
            )
            tier_plans.append(tier_plan)
            inherited_plan = tier_plan
        tier_plans = list(tier_plans)
        tier_plans = _annotate_identical_tiers(tier_plans)

        return PlanBuildResult(
            schema_version=SCHEMA_VERSION,
            strategy_version=strategy_version,
            trace_id=request.trace_id,
            patient_id=request.patient_id,
            as_of_date=request.as_of_date,
            tiers=tier_plans,
            rule_set_versions=tuple(
                sorted({item.rule_set_version for item in ordered if item.rule_set_version})
            ),
            price_catalog_version=catalog.catalog_version,
            notes=_result_notes(
                request,
                mandatory,
                selectable,
                forbidden,
                duplicates,
                duplicate_conflicts,
            ),
            disclosures=DISCLOSURES,
        )

    def _build_tier(
        self,
        *,
        tier: PlanTier,
        mandatory: Sequence[PlanCandidate],
        selectable: Sequence[PlanCandidate],
        forbidden: Sequence[PlanCandidate],
        duplicates: Sequence[PlanCandidate],
        duplicate_conflicts: Sequence[PlanConflict],
        inherited_plan: TierPlan | None,
        by_id: dict[str, PlanCandidate],
        catalog: PriceCatalog,
        request: PlanBuildRequest,
        strategy_version: str,
    ) -> TierPlan:
        policy = TIER_POLICIES[tier]
        selected: list[SelectedPlanItem] = []
        excluded: list[ExcludedPlanItem] = []
        conflicts: list[PlanConflict] = list(duplicate_conflicts)
        lower_tier = inherited_plan.tier if inherited_plan is not None else None
        inherited_items = list(inherited_plan.items) if inherited_plan is not None else []
        inherited_ids = {item.exam_item_id for item in inherited_items}

        for item in inherited_items:
            candidate = by_id[item.exam_item_id]
            origin = item.inherited_from or lower_tier
            selected.append(
                _select(
                    candidate,
                    tier,
                    request,
                    catalog,
                    selection_reason=(
                        f"承自{origin.value}档：{_score_text(candidate)}，"
                        f"{_cost_text(_lookup_price(candidate, request, catalog))}；"
                        "本档在低档结果之上扩充，不删除已选项目"
                    ),
                    inherited_from=origin,
                )
            )

        for candidate in forbidden:
            excluded.append(
                _excluded(
                    candidate,
                    ExclusionReason.RULE_BLOCKED
                    if candidate.rule_status is CandidateRuleStatus.BLOCKED
                    else ExclusionReason.RULE_DEFERRED,
                    _rule_reason(candidate),
                )
            )
        for candidate in duplicates:
            excluded.append(
                _excluded(
                    candidate,
                    ExclusionReason.DUPLICATE_CANDIDATE,
                    "同一项目重复出现，已按保守策略合并：取最高分并保留最严格的规则结论",
                )
            )

        if len(mandatory) > policy.max_items:
            conflicts.append(
                PlanConflict(
                    code=ConflictCode.REVIEW_ITEMS_EXCEED_TIER_SIZE,
                    message=(
                        f"应复核项目 {len(mandatory)} 个，超过本档项目数上限 {policy.max_items}；"
                        "应复核项目优先保留，可选项目被截断"
                    ),
                    exam_item_ids=tuple(item.exam_item_id for item in mandatory),
                )
            )

        for candidate in mandatory:
            if candidate.exam_item_id in inherited_ids:
                continue
            selected.append(
                _select(
                    candidate,
                    tier,
                    request,
                    catalog,
                    selection_reason=_review_reason(candidate, request, catalog),
                )
            )

        optional_slots = max(policy.max_items - len(selected), 0)
        optional_selected = 0
        for candidate in selectable:
            if candidate.exam_item_id in inherited_ids:
                continue
            price = _lookup_price(candidate, request, catalog)
            if optional_selected >= optional_slots:
                excluded.append(
                    _excluded(
                        candidate,
                        ExclusionReason.TIER_ITEM_LIMIT,
                        f"本档项目数上限 {policy.max_items} 已满，"
                        f"其中 {len(selected)} 项来自低档结果与应复核项目",
                    )
                )
                continue
            if candidate.radiation and not policy.allow_radiation:
                excluded.append(
                    _excluded(
                        candidate,
                        ExclusionReason.TIER_RADIATION_POLICY,
                        "本档不选入含辐射项目",
                    )
                )
                continue
            if candidate.cost_level not in policy.allowed_cost_levels:
                excluded.append(
                    _excluded(
                        candidate,
                        ExclusionReason.TIER_COST_LEVEL_POLICY,
                        f"本档仅选入费用等级 {_levels(policy)} 的项目",
                    )
                )
                continue
            if request.budget is not None and price is not None:
                budget_currency = request.budget.currency
                # 只累计与预算相同币种的金额，其它币种无法换算时不参与比较。
                if price.currency == budget_currency:
                    known_total = _currency_total(selected, budget_currency)
                    if known_total + price.amount_cents > request.budget.limit_cents:
                        excluded.append(
                            _excluded(
                                candidate,
                                ExclusionReason.BUDGET_LIMIT,
                                "加入后同币种已知费用将超过预算 "
                                f"{format_amount(request.budget.limit_cents, budget_currency)}"
                                f"（当前 {format_amount(known_total, budget_currency)}）",
                            )
                        )
                        continue
            selected.append(
                _select(
                    candidate,
                    tier,
                    request,
                    catalog,
                    selection_reason=_policy_reason(candidate, policy, price),
                )
            )
            optional_selected += 1

        selected.sort(key=lambda item: (-(item.score or 0.0), item.code, item.exam_item_id))
        ranked = tuple(
            item.model_copy(update={"rank": index}) for index, item in enumerate(selected, 1)
        )
        cost_summary = _cost_summary(ranked, request)
        budget_status, budget_note, budget_conflicts = _evaluate_budget(
            cost_summary, request.budget
        )
        conflicts.extend(budget_conflicts)
        return TierPlan(
            tier=tier,
            strategy_version=strategy_version,
            items=ranked,
            excluded=tuple(excluded),
            cost_summary=cost_summary,
            budget_status=budget_status,
            budget_note=budget_note,
            conflicts=tuple(conflicts),
            selection_note=_selection_note(tier, policy, ranked, len(selectable)),
        )


def build_plan(request: PlanBuildRequest) -> PlanBuildResult:
    """便捷入口：使用默认策略构建三档方案。"""

    return PlanBuilder().build(request)


def to_snapshot(
    result: PlanBuildResult, *, adopted_tier: PlanTier = PlanTier.STANDARD
) -> dict[str, Any]:
    """把构建结果转成可直接写入 ``AIReport.content`` 的快照字典。

    已确认的接口口径：一次请求返回三档对比，``Recommendation.plan_tier`` 记录实际采纳的
    档位（默认 ``standard``）。快照内是构建时冻结的价格副本，之后调整价格目录不会改变
    已保存的方案；``adopted_plan`` 提供与旧版单份草稿同形的展示结构。
    """

    if adopted_tier not in {plan.tier for plan in result.tiers}:
        raise ValueError(f"采纳档位 {adopted_tier} 不在本次构建结果中")
    payload = result.model_dump(mode="json")
    payload["tier_mode"] = SNAPSHOT_TIER_MODE
    payload["adopted_tier"] = adopted_tier.value
    payload["adopted_plan"] = next(
        plan.model_dump(mode="json") for plan in result.tiers if plan.tier is adopted_tier
    )
    return payload


def _deduplicate(
    candidates: Sequence[PlanCandidate],
) -> tuple[list[PlanCandidate], list[PlanCandidate], list[PlanConflict]]:
    """按保守策略合并重复候选：分数取最高，规则结论取最严格，说明与证据取并集。

    模型分数或评分更高的一条不得覆盖禁止（BLOCKED）或暂缓（DEFERRED）结论。
    """

    groups: dict[str, list[PlanCandidate]] = {}
    dropped: list[PlanCandidate] = []
    for candidate in candidates:
        groups.setdefault(candidate.exam_item_id, []).append(candidate)

    kept: list[PlanCandidate] = []
    conflicts: list[PlanConflict] = []
    for group in groups.values():
        if len(group) == 1:
            kept.append(group[0])
            continue
        merged, status_conflict = _merge_duplicates(group)
        kept.append(merged)
        dropped.extend(item for item in group if item is not merged)
        if status_conflict:
            statuses = "、".join(
                sorted({item.rule_status.value for item in group}, key=_status_rank)
            )
            conflicts.append(
                PlanConflict(
                    code=ConflictCode.DUPLICATE_RULE_STATUS_CONFLICT,
                    message=(
                        f"重复候选 {merged.code} 存在不同规则结论（{statuses}）；"
                        f"已按保守策略取 {merged.rule_status.value}，模型分数不覆盖规则结论。"
                    ),
                    exam_item_ids=(merged.exam_item_id,),
                )
            )
    return kept, dropped, conflicts


_STATUS_PRECEDENCE: tuple[CandidateRuleStatus, ...] = (
    CandidateRuleStatus.BLOCKED,
    CandidateRuleStatus.DEFERRED,
    CandidateRuleStatus.REVIEW_REQUIRED,
    CandidateRuleStatus.NOT_CONFIGURED,
    CandidateRuleStatus.ALLOWED,
)


def _status_rank(status: CandidateRuleStatus) -> int:
    return _STATUS_PRECEDENCE.index(status)


def _merge_duplicates(
    group: Sequence[PlanCandidate],
) -> tuple[PlanCandidate, bool]:
    """返回合并后的候选，以及是否存在不同规则结论。"""

    scores = [item.score for item in group if item.score is not None]
    ranked = sorted(
        group,
        key=lambda item: (_status_rank(item.rule_status), -(item.score or 0.0), item.code),
    )
    strictest = ranked[0]
    notes = tuple(dict.fromkeys(note for item in group for note in item.rule_notes))
    evidence = tuple(dict.fromkeys(ref for item in group for ref in item.rule_evidence_refs))
    versions = sorted({item.rule_set_version for item in group if item.rule_set_version})
    merged = strictest.model_copy(
        update={
            "score": max(scores) if scores else None,
            "rule_notes": notes,
            "rule_evidence_refs": evidence,
            "rule_set_version": versions[0] if len(versions) == 1 else strictest.rule_set_version,
        }
    )
    return merged, len({item.rule_status for item in group}) > 1


def _order_candidates(candidates: Sequence[PlanCandidate]) -> list[PlanCandidate]:
    return sorted(candidates, key=lambda item: (-(item.score or 0.0), item.code, item.exam_item_id))


def _lookup_price(
    candidate: PlanCandidate, request: PlanBuildRequest, catalog: PriceCatalog
) -> ExamItemPrice | None:
    return catalog.lookup(
        candidate.code,
        request.as_of_date,
        institution=request.institution,
        region=request.region,
    )


def _snapshot(price: ExamItemPrice | None, catalog: PriceCatalog) -> PriceSnapshot:
    if price is None:
        return PriceSnapshot(catalog_version=catalog.catalog_version)
    return PriceSnapshot(
        amount_cents=price.amount_cents,
        currency=price.currency,
        source=price.source,
        source_url=price.source_url,
        institution=price.institution,
        region=price.region,
        effective_from=price.effective_from,
        is_demo_price=price.is_demo_price,
        catalog_version=catalog.catalog_version,
    )


def _select(
    candidate: PlanCandidate,
    tier: PlanTier,
    request: PlanBuildRequest,
    catalog: PriceCatalog,
    *,
    selection_reason: str,
    inherited_from: PlanTier | None = None,
) -> SelectedPlanItem:
    price = _lookup_price(candidate, request, catalog)
    return SelectedPlanItem(
        exam_item_id=candidate.exam_item_id,
        code=candidate.code,
        name=candidate.name,
        category=candidate.category,
        radiation=candidate.radiation,
        tier=tier,
        rank=1,
        score=candidate.score,
        rule_status=candidate.rule_status,
        requires_review=candidate.rule_status.requires_review,
        rule_set_version=candidate.rule_set_version,
        rule_notes=candidate.rule_notes,
        rule_evidence_refs=candidate.rule_evidence_refs,
        inherited_from=inherited_from,
        selection_reason=selection_reason,
        cost_status=CostStatus.PRICED if price else CostStatus.UNPRICED,
        price=_snapshot(price, catalog),
    )


def _excluded(
    candidate: PlanCandidate, reason_code: ExclusionReason, reason: str
) -> ExcludedPlanItem:
    return ExcludedPlanItem(
        exam_item_id=candidate.exam_item_id,
        code=candidate.code,
        name=candidate.name,
        reason_code=reason_code,
        reason=reason,
    )


def _rule_reason(candidate: PlanCandidate) -> str:
    detail = "；".join(candidate.rule_notes)
    label = "规则禁止" if candidate.rule_status is CandidateRuleStatus.BLOCKED else "规则要求暂缓"
    return f"{label}：{detail}" if detail else f"{label}：该结论在任何档位都不重新选入"


def _levels(policy: TierPolicy) -> str:
    return "/".join(level.value for level in policy.allowed_cost_levels)


def _cost_text(price: ExamItemPrice | None) -> str:
    if price is None:
        return "费用未知"
    suffix = "（演示价）" if price.is_demo_price else ""
    return f"费用 {format_amount(price.amount_cents, price.currency)}{suffix}"


def _score_text(candidate: PlanCandidate) -> str:
    return "无匹配分数" if candidate.score is None else f"匹配分数 {candidate.score:.4f}"


def _review_reason(
    candidate: PlanCandidate, request: PlanBuildRequest, catalog: PriceCatalog
) -> str:
    price = _lookup_price(candidate, request, catalog)
    return (
        f"规则要求复核（{candidate.rule_status.value}）：{_score_text(candidate)}，"
        f"{_cost_text(price)}；各档位均保留，不因预算或档位策略删除"
    )


def _policy_reason(
    candidate: PlanCandidate, policy: TierPolicy, price: ExamItemPrice | None
) -> str:
    return f"{policy.description}：{_score_text(candidate)}，{_cost_text(price)}"


def _currency_total(selected: Sequence[SelectedPlanItem], currency: str) -> int:
    """指定币种的已知费用小计；不同币种从不合并相加。"""

    return sum(
        item.price.amount_cents
        for item in selected
        if item.price.currency == currency and item.price.amount_cents is not None
    )


def _cost_summary(selected: Sequence[SelectedPlanItem], request: PlanBuildRequest) -> CostSummary:
    totals: dict[str, int] = {}
    unpriced: list[str] = []
    includes_demo = False
    for item in selected:
        amount = item.price.amount_cents
        currency = item.price.currency
        if amount is None or currency is None:
            unpriced.append(item.code)
            continue
        totals[currency] = totals.get(currency, 0) + amount
        includes_demo = includes_demo or item.price.is_demo_price
    mixed = len(totals) > 1
    currency = None if mixed else next(iter(sorted(totals)), None)
    if currency is None and not mixed and request.budget is not None:
        currency = request.budget.currency
    is_complete = not unpriced
    return CostSummary(
        currency=currency,
        known_total_cents=None if mixed else sum(totals.values()),
        priced_item_count=sum(1 for item in selected if item.cost_status is CostStatus.PRICED),
        unpriced_item_count=len(unpriced),
        unpriced_item_codes=tuple(unpriced),
        is_complete=is_complete,
        mixed_currency=mixed,
        per_currency_totals=dict(sorted(totals.items())),
        includes_demo_price=includes_demo,
        disclosure=_cost_disclosure(totals, unpriced, includes_demo),
    )


def _cost_disclosure(totals: dict[str, int], unpriced: Sequence[str], includes_demo: bool) -> str:
    if len(totals) > 1:
        parts = "、".join(
            f"{format_amount(amount, currency)}" for currency, amount in sorted(totals.items())
        )
        return f"包含多种币种（{parts}），未合并为单一合计；未知价格项目 {len(unpriced)} 个。"
    if totals:
        currency, amount = next(iter(sorted(totals.items())))
        known = f"已知费用小计 {format_amount(amount, currency)}"
    else:
        known = "已知费用小计 0.00"
    if unpriced:
        return f"{known}；另有 {len(unpriced)} 个项目价格未知，不能据此声称总价完整或保证不超预算。"
    if includes_demo:
        return f"{known}；包含演示价，仅用于工程演示，不能作为真实收费依据。"
    return f"{known}；价格来自记录的可核验来源，实际收费以机构为准。"


def _evaluate_budget(
    summary: CostSummary, budget: BudgetSpec | None
) -> tuple[BudgetStatus, str, list[PlanConflict]]:
    if budget is None:
        return (
            BudgetStatus.NOT_PROVIDED,
            "未提供预算偏好：档位差异只来自项目组合策略。",
            [],
        )
    limit = budget.limit_cents
    limit_text = format_amount(limit, budget.currency)
    budget_total = summary.per_currency_totals.get(budget.currency, 0)
    other_currencies = {
        currency: amount
        for currency, amount in summary.per_currency_totals.items()
        if currency != budget.currency
    }
    if budget_total > limit:
        return (
            BudgetStatus.OVER_BUDGET,
            f"已知 {budget.currency} 费用小计 {format_amount(budget_total, budget.currency)} "
            f"超过预算 {limit_text}；"
            "应复核项目未被删除，请在方案说明中记录冲突。",
            [
                PlanConflict(
                    code=ConflictCode.BUDGET_EXCEEDED,
                    message=(
                        f"已知 {budget.currency} 费用 "
                        f"{format_amount(budget_total, budget.currency)} 超过预算 {limit_text}；"
                        "规则要求复核的项目全部保留。"
                    ),
                )
            ],
        )
    if other_currencies:
        detail = "、".join(
            f"{format_amount(amount, currency)}"
            for currency, amount in sorted(other_currencies.items())
        )
        return (
            BudgetStatus.UNDETERMINED,
            f"已知 {budget.currency} 小计 {format_amount(budget_total, budget.currency)} "
            f"未超过预算 {limit_text}，但另有其他币种项目（{detail}）无法换算，"
            "总预算不可判定。",
            [
                PlanConflict(
                    code=ConflictCode.MIXED_CURRENCY,
                    message=(
                        f"方案包含与预算不同币种的项目（{detail}），未做换算与合并比较，"
                        "总预算不可判定。"
                    ),
                )
            ],
        )
    if not summary.is_complete:
        return (
            BudgetStatus.UNKNOWN_PRICES,
            f"已知费用小计 {format_amount(budget_total, budget.currency)} 未超过预算 {limit_text}，"
            f"但 {summary.unpriced_item_count} 个项目价格未知，无法保证不超预算。",
            [
                PlanConflict(
                    code=ConflictCode.UNKNOWN_PRICE_BLOCKS_TOTAL,
                    message=(
                        f"{summary.unpriced_item_count} 个项目价格未知，"
                        "不能声称已知费用就是完整总价。"
                    ),
                    exam_item_ids=summary.unpriced_item_codes,
                )
            ],
        )
    return (
        BudgetStatus.WITHIN_BUDGET,
        f"已知费用小计 {format_amount(budget_total, budget.currency)} 在预算 {limit_text} 之内。",
        [],
    )


def _selection_note(
    tier: PlanTier, policy: TierPolicy, items: Sequence[SelectedPlanItem], selectable: int
) -> str:
    inherited = sum(1 for item in items if item.inherited_from is not None)
    base = (
        f"{policy.description}；上限 {policy.max_items} 项，"
        f"可选候选 {selectable} 个，本档选入 {len(items)} 项。"
    )
    if inherited:
        base += f" 其中 {inherited} 项承自低档结果，本档新增 {len(items) - inherited} 项。"
    if not items:
        return f"{base} 本档没有可保留的项目。"
    return base


def _annotate_identical_tiers(tiers: Sequence[TierPlan]) -> tuple[TierPlan, ...]:
    annotated: list[TierPlan] = []
    for tier_plan in tiers:
        current = {item.exam_item_id for item in tier_plan.items}
        identical = tuple(
            other.tier
            for other in tiers
            if other.tier is not tier_plan.tier and {i.exam_item_id for i in other.items} == current
        )
        if not identical:
            annotated.append(tier_plan)
            continue
        names = "、".join(other.value for other in identical)
        reasons = {item.reason_code for item in tier_plan.excluded}
        detail = (
            "候选目录中符合本档策略的可选项目不足"
            if not reasons
            else "被档位策略或预算排除的项目与其它档位相同"
        )
        conflicts = (
            *tier_plan.conflicts,
            PlanConflict(
                code=ConflictCode.TIERS_NOT_DISTINCT,
                message=f"本档与 {names} 档的项目集合相同：{detail}。",
            ),
        )
        annotated.append(
            tier_plan.model_copy(
                update={
                    "identical_to": identical,
                    "conflicts": conflicts,
                    "selection_note": (
                        f"{tier_plan.selection_note} 与 {names} 档项目集合相同：{detail}。"
                    ),
                }
            )
        )
    return tuple(annotated)


def _result_notes(
    request: PlanBuildRequest,
    mandatory: Sequence[PlanCandidate],
    selectable: Sequence[PlanCandidate],
    forbidden: Sequence[PlanCandidate],
    duplicates: Sequence[PlanCandidate],
    duplicate_conflicts: Sequence[PlanConflict],
) -> tuple[str, ...]:
    notes: list[str] = []
    if not request.candidates:
        notes.append("候选目录为空，未生成任何档位；请先维护体检项目目录。")
        return tuple(notes)
    if duplicates:
        notes.append(
            f"输入包含 {len(duplicates)} 条重复候选，已按保守策略合并（分数取最高，"
            "规则结论取最严格）。"
        )
    if duplicate_conflicts:
        notes.append(
            f"其中 {len(duplicate_conflicts)} 个项目的重复记录规则结论不一致，已按最严格结论处理。"
        )
    if forbidden and not mandatory and not selectable:
        notes.append("全部候选都被规则禁止或要求暂缓，三个档位都没有可保留项目。")
    if not forbidden and not mandatory and not selectable:
        notes.append("没有可参与档位选取的候选项目。")
    if not request.price_catalog.prices:
        notes.append("未提供价格目录：所有项目费用未知，不生成总价。")
    if not mandatory:
        notes.append("本次没有规则要求复核的项目；输出仍为待复核草稿。")
    return tuple(notes)
