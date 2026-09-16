from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.rules.models import FinalRuleStatus


class RuleOutcomeAuditRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    selected: bool
    final_status: FinalRuleStatus
    review_acknowledged: bool = False


class RuleViolationMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    selected_count: int = Field(ge=0)
    violation_count: int = Field(ge=0)
    rate: float = Field(ge=0, le=1)


def rule_violation_rate(records: Sequence[RuleOutcomeAuditRecord]) -> RuleViolationMetrics:
    """Measure unsafe selections after rule evaluation.

    A selected BLOCKED/DEFERRED item is always a violation. A selected
    REVIEW_REQUIRED item is a violation until an authorized review is acknowledged.
    """

    selected = [record for record in records if record.selected]
    violations = [
        record
        for record in selected
        if record.final_status in {FinalRuleStatus.BLOCKED, FinalRuleStatus.DEFERRED}
        or (
            record.final_status is FinalRuleStatus.REVIEW_REQUIRED
            and not record.review_acknowledged
        )
    ]
    return RuleViolationMetrics(
        selected_count=len(selected),
        violation_count=len(violations),
        rate=len(violations) / len(selected) if selected else 0.0,
    )
