from app.rules.metrics import RuleOutcomeAuditRecord, rule_violation_rate
from app.rules.models import FinalRuleStatus


def test_rule_violation_rate_counts_selected_unsafe_outcomes() -> None:
    records = [
        RuleOutcomeAuditRecord(selected=True, final_status=FinalRuleStatus.BLOCKED),
        RuleOutcomeAuditRecord(selected=True, final_status=FinalRuleStatus.DEFERRED),
        RuleOutcomeAuditRecord(
            selected=True,
            final_status=FinalRuleStatus.REVIEW_REQUIRED,
            review_acknowledged=False,
        ),
        RuleOutcomeAuditRecord(selected=True, final_status=FinalRuleStatus.ALLOWED),
        RuleOutcomeAuditRecord(selected=False, final_status=FinalRuleStatus.BLOCKED),
    ]

    metrics = rule_violation_rate(records)

    assert metrics.selected_count == 4
    assert metrics.violation_count == 3
    assert metrics.rate == 0.75


def test_acknowledged_review_and_empty_selection_are_not_violations() -> None:
    acknowledged = rule_violation_rate(
        [
            RuleOutcomeAuditRecord(
                selected=True,
                final_status=FinalRuleStatus.REVIEW_REQUIRED,
                review_acknowledged=True,
            )
        ]
    )
    empty = rule_violation_rate(
        [RuleOutcomeAuditRecord(selected=False, final_status=FinalRuleStatus.BLOCKED)]
    )

    assert acknowledged.rate == 0.0
    assert empty.rate == 0.0
    assert empty.selected_count == 0
