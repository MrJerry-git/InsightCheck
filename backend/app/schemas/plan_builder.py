"""三档方案构建的输入输出约定。

这些模型只描述数据，不读写数据库；接入 API 由负责人协调后再做。
约定要点：档位表达项目组合与预算偏好，不表达疾病风险或医学必要性。
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import CostLevel, PlanTier
from app.rules.models import FinalRuleStatus, RuleEvaluationResult
from app.services.pricing import PriceCatalog

SCHEMA_VERSION = "plan-builder-contract-v1"
TIER_ORDER: tuple[PlanTier, ...] = (PlanTier.SIMPLIFIED, PlanTier.STANDARD, PlanTier.DEEP)


class CandidateRuleStatus(StrEnum):
    """候选项目在方案层的规则状态，直接对应规则引擎的输出。"""

    ALLOWED = "ALLOWED"
    DEFERRED = "DEFERRED"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_CONFIGURED = "NOT_CONFIGURED"

    @classmethod
    def from_final_status(cls, status: FinalRuleStatus) -> "CandidateRuleStatus":
        return cls(status.value)

    @classmethod
    def from_rule_evaluation(cls, evaluation: RuleEvaluationResult) -> "CandidateRuleStatus":
        """未配置任何启用规则时标记为 NOT_CONFIGURED，不视为审核通过。"""

        if not any(record.enabled for record in evaluation.execution_trace):
            return cls.NOT_CONFIGURED
        return cls.from_final_status(evaluation.final_status)

    @property
    def forbids_selection(self) -> bool:
        """规则禁止项：任何档位都不得选入。"""

        return self in {CandidateRuleStatus.BLOCKED, CandidateRuleStatus.DEFERRED}

    @property
    def requires_review(self) -> bool:
        return self is CandidateRuleStatus.REVIEW_REQUIRED


class BudgetStatus(StrEnum):
    WITHIN_BUDGET = "within_budget"
    OVER_BUDGET = "over_budget"
    UNKNOWN_PRICES = "unknown_prices"
    UNDETERMINED = "undetermined"
    NOT_PROVIDED = "not_provided"


class CostStatus(StrEnum):
    PRICED = "priced"
    UNPRICED = "unpriced"


class ExclusionReason(StrEnum):
    RULE_BLOCKED = "rule_blocked"
    RULE_DEFERRED = "rule_deferred"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    TIER_ITEM_LIMIT = "tier_item_limit"
    TIER_RADIATION_POLICY = "tier_radiation_policy"
    TIER_COST_LEVEL_POLICY = "tier_cost_level_policy"
    BUDGET_LIMIT = "budget_limit"


class ConflictCode(StrEnum):
    BUDGET_EXCEEDED = "budget_exceeded"
    UNKNOWN_PRICE_BLOCKS_TOTAL = "unknown_price_blocks_total"
    MIXED_CURRENCY = "mixed_currency"
    DUPLICATE_RULE_STATUS_CONFLICT = "duplicate_rule_status_conflict"
    REVIEW_ITEMS_EXCEED_TIER_SIZE = "review_items_exceed_tier_size"
    TIERS_NOT_DISTINCT = "tiers_not_distinct"
    NO_ELIGIBLE_ITEM = "no_eligible_item"
    EMPTY_CANDIDATE_CATALOG = "empty_candidate_catalog"


class BudgetSpec(BaseModel):
    """预算偏好：只约束已知费用，不改变规则结论。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    limit_cents: int = Field(ge=0)
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=300)


class PlanCandidate(BaseModel):
    """方案构建所需的单个候选项目及其规则结论（由规则引擎产出，不在本模块重算）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exam_item_id: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    radiation: bool = False
    cost_level: CostLevel
    score: float | None = Field(default=None, ge=0, le=1)
    rule_status: CandidateRuleStatus = CandidateRuleStatus.NOT_CONFIGURED
    rule_set_version: str | None = Field(default=None, max_length=64)
    rule_notes: tuple[str, ...] = ()
    rule_evidence_refs: tuple[str, ...] = ()


class PriceSnapshot(BaseModel):
    """方案快照中冻结的价格副本；之后价格调整不改变已保存方案。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount_cents: int | None = Field(default=None, ge=0)
    currency: str | None = None
    source: str | None = None
    source_url: str | None = None
    institution: str | None = None
    region: str | None = None
    effective_from: date | None = None
    is_demo_price: bool = False
    catalog_version: str | None = None


class SelectedPlanItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    exam_item_id: str
    code: str
    name: str
    category: str
    radiation: bool
    tier: PlanTier
    rank: int = Field(ge=1)
    score: float | None = Field(default=None, ge=0, le=1)
    rule_status: CandidateRuleStatus
    requires_review: bool
    rule_set_version: str | None = Field(default=None, max_length=64)
    rule_notes: tuple[str, ...] = ()
    rule_evidence_refs: tuple[str, ...] = ()
    inherited_from: PlanTier | None = None
    selection_reason: str = Field(min_length=1)
    cost_status: CostStatus
    price: PriceSnapshot


class ExcludedPlanItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    exam_item_id: str
    code: str
    name: str
    reason_code: ExclusionReason
    reason: str = Field(min_length=1)


class CostSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: str | None = None
    known_total_cents: int | None = Field(default=None, ge=0)
    priced_item_count: int = Field(ge=0)
    unpriced_item_count: int = Field(ge=0)
    unpriced_item_codes: tuple[str, ...] = ()
    is_complete: bool
    mixed_currency: bool
    per_currency_totals: dict[str, int] = Field(default_factory=dict)
    includes_demo_price: bool = False
    disclosure: str = Field(min_length=1)


class PlanConflict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ConflictCode
    message: str = Field(min_length=1)
    exam_item_ids: tuple[str, ...] = ()


class TierPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: PlanTier
    strategy_version: str
    items: tuple[SelectedPlanItem, ...]
    excluded: tuple[ExcludedPlanItem, ...]
    cost_summary: CostSummary
    budget_status: BudgetStatus
    budget_note: str = Field(min_length=1)
    conflicts: tuple[PlanConflict, ...] = ()
    identical_to: tuple[PlanTier, ...] = ()
    selection_note: str = Field(min_length=1)


class PlanBuildRequest(BaseModel):
    """方案构建输入：候选、规则结论、价格目录、预算偏好。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_id: str = Field(min_length=1, max_length=100)
    patient_id: str = Field(min_length=1)
    as_of_date: date
    candidates: tuple[PlanCandidate, ...]
    price_catalog: PriceCatalog = PriceCatalog()
    budget: BudgetSpec | None = None
    institution: str | None = Field(default=None, max_length=200)
    region: str | None = Field(default=None, max_length=100)
    tiers: tuple[PlanTier, ...] = TIER_ORDER
    strategy_version: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_tiers(self) -> "PlanBuildRequest":
        if not self.tiers:
            raise ValueError("至少需要一个档位")
        if len(set(self.tiers)) != len(self.tiers):
            raise ValueError("档位不能重复")
        unknown = [tier for tier in self.tiers if tier not in TIER_ORDER]
        if unknown:
            raise ValueError(f"不支持的档位：{unknown}")
        return self


class PlanBuildResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    strategy_version: str
    trace_id: str
    patient_id: str
    as_of_date: date
    tiers: tuple[TierPlan, ...]
    rule_set_versions: tuple[str, ...] = ()
    price_catalog_version: str | None = None
    notes: tuple[str, ...] = ()
    disclosures: tuple[str, ...] = ()
