from datetime import date

from app.rules.engine import RuleEngine
from app.rules.models import (
    CandidateExamItem,
    ExamHistoryFact,
    FinalRuleStatus,
    LesionHistoryFact,
    MedicalRuleDefinition,
    PatientContext,
    RiskPredictionFact,
    RuleAction,
    RuleEvaluationRequest,
    RuleType,
)


def make_request(**updates: object) -> RuleEvaluationRequest:
    base = RuleEvaluationRequest(
        patient=PatientContext(
            patient_id="patient-1",
            as_of_date=date(2026, 3, 1),
            age=42,
            sex="male",
        ),
        exam_item=CandidateExamItem(
            exam_item_id="exam-item-ct",
            code="CHEST_CT",
            name="胸部 CT",
            category="imaging",
            body_part="CHEST",
            radiation=True,
            functional_groups=["CHEST_CROSS_SECTIONAL_IMAGING"],
            recommended_interval_months=12,
        ),
        deepfm_score=0.91,
        trace_id="trace-default",
    )
    return base.model_copy(update=updates)


def make_rule(
    rule_code: str,
    rule_type: RuleType,
    action: RuleAction,
    condition: dict[str, object],
    *,
    priority: int = 50,
    enabled: bool = True,
    version: str = "demo-rule-v1",
) -> MedicalRuleDefinition:
    return MedicalRuleDefinition(
        rule_code=rule_code,
        rule_type=rule_type,
        condition=condition,
        action=action,
        priority=priority,
        source="演示规则：产品测试基线，不作为临床指南",
        version=version,
        enabled=enabled,
    )


def test_interval_rule_defers_exam_inside_minimum_interval() -> None:
    request = RuleEvaluationRequest(
        patient=PatientContext(
            patient_id="patient-1",
            as_of_date=date(2026, 3, 1),
            age=42,
            sex="male",
        ),
        exam_item=CandidateExamItem(
            exam_item_id="exam-item-ct",
            code="CHEST_CT",
            name="胸部 CT",
            category="imaging",
            radiation=True,
            recommended_interval_months=12,
        ),
        deepfm_score=0.91,
        exam_history=[
            ExamHistoryFact(
                exam_item_id="exam-item-ct",
                exam_code="CHEST_CT",
                performed_at=date(2026, 1, 1),
                result_status="completed",
            )
        ],
        trace_id="trace-interval",
    )
    rule = MedicalRuleDefinition(
        rule_code="INTERVAL.CHEST_CT.MIN_12M",
        rule_type=RuleType.INTERVAL,
        condition={"minimum_months": 12},
        action=RuleAction.DEFER,
        priority=80,
        source="演示规则：产品测试基线，不作为临床指南",
        version="demo-rule-v1",
        enabled=True,
    )

    result = RuleEngine().evaluate(request, [rule])

    assert result.final_status is FinalRuleStatus.DEFERRED
    assert result.deepfm_score == 0.91
    assert result.rule_decisions[0].action is RuleAction.DEFER
    assert result.rule_decisions[0].version == "demo-rule-v1"
    assert result.rule_decisions[0].reason
    assert result.execution_trace[0].matched is True


def test_duplicate_rule_detects_functionally_overlapping_selected_item() -> None:
    selected = CandidateExamItem(
        exam_item_id="exam-item-mri",
        code="CHEST_MRI",
        name="胸部 MRI",
        category="imaging",
        body_part="CHEST",
        functional_groups=["CHEST_CROSS_SECTIONAL_IMAGING"],
    )
    request = make_request(selected_exam_items=[selected])
    rule = make_rule(
        "DUPLICATE.CHEST.IMAGING",
        RuleType.DUPLICATE,
        RuleAction.DEFER,
        {"minimum_overlap_count": 1},
    )

    result = RuleEngine().evaluate(request, [rule])

    assert result.final_status is FinalRuleStatus.DEFERRED
    assert "功能重叠" in result.rule_decisions[0].reason


def test_radiation_rule_reduces_score_for_recent_related_exposure() -> None:
    request = make_request(
        exam_history=[
            ExamHistoryFact(
                exam_item_id="prior-radiation-exam",
                exam_code="CHEST_XRAY",
                performed_at=date(2026, 1, 15),
                result_status="completed",
                body_part="CHEST",
                radiation=True,
                evidence_refs=["exam-history:prior-radiation-exam"],
            )
        ]
    )
    rule = make_rule(
        "RADIATION.CHEST.RECENT",
        RuleType.RADIATION,
        RuleAction.REDUCE,
        {"lookback_months": 6, "same_body_part": True, "score_delta": 0.25},
    )

    result = RuleEngine().evaluate(request, [rule])

    assert result.final_status is FinalRuleStatus.ALLOWED
    assert result.adjusted_score == 0.66
    assert result.rule_decisions[0].score_delta == -0.25


def test_age_and_gender_rules_block_wrong_target_population() -> None:
    age_rule = make_rule(
        "AGE.ONLY_50_PLUS",
        RuleType.AGE,
        RuleAction.BLOCK,
        {"allowed_min_age": 50},
        priority=70,
    )
    gender_rule = make_rule(
        "GENDER.FEMALE_ONLY",
        RuleType.GENDER,
        RuleAction.BLOCK,
        {"allowed_genders": ["female"]},
        priority=60,
    )

    result = RuleEngine().evaluate(make_request(), [age_rule, gender_rule])

    assert result.final_status is FinalRuleStatus.BLOCKED
    assert result.adjusted_score == 0.0
    assert {decision.rule_type for decision in result.rule_decisions} == {
        RuleType.AGE,
        RuleType.GENDER,
    }


def test_risk_and_lesion_rules_consume_structured_facts() -> None:
    request = make_request(
        risk_predictions=[
            RiskPredictionFact(
                risk_code="LUNG_RISK",
                probability=0.82,
                model_version="risk-model-v1",
                evidence_refs=["risk:LUNG_RISK:2026"],
            )
        ],
        lesion_history=[
            LesionHistoryFact(
                lesion_type="PULMONARY_NODULE",
                location="RIGHT_UPPER_LOBE",
                last_exam_date=date(2025, 3, 1),
                match_status="MATCHED",
                growing=True,
                evidence_refs=["lesion-track:demo-1"],
            )
        ],
    )
    risk_rule = make_rule(
        "RISK.LUNG.BOOST",
        RuleType.RISK,
        RuleAction.BOOST,
        {"risk_code": "LUNG_RISK", "minimum_probability": 0.8, "score_delta": 0.05},
    )
    lesion_rule = make_rule(
        "LESION.PULMONARY_GROWING.REVIEW",
        RuleType.LESION_FOLLOWUP,
        RuleAction.REVIEW_REQUIRED,
        {"lesion_type": "PULMONARY_NODULE", "growing": True},
    )

    result = RuleEngine().evaluate(request, [risk_rule, lesion_rule])

    assert result.final_status is FinalRuleStatus.REVIEW_REQUIRED
    assert {decision.rule_type for decision in result.rule_decisions} == {
        RuleType.RISK,
        RuleType.LESION_FOLLOWUP,
    }


def test_missing_critical_history_requires_review_instead_of_assuming_safe() -> None:
    rule = make_rule(
        "MISSING_DATA.REQUIRED_CONTEXT",
        RuleType.MISSING_DATA,
        RuleAction.REVIEW_REQUIRED,
        {"required_fields": ["exam_history", "risk_predictions"]},
        priority=100,
    )

    result = RuleEngine().evaluate(make_request(), [rule])

    assert result.final_status is FinalRuleStatus.REVIEW_REQUIRED
    assert "缺少" in result.rule_decisions[0].reason


def test_block_wins_over_higher_deepfm_score_and_boost() -> None:
    request = make_request(
        deepfm_score=0.99,
        risk_predictions=[
            RiskPredictionFact(
                risk_code="LUNG_RISK", probability=0.9, model_version="risk-model-v1"
            )
        ],
    )
    boost = make_rule(
        "RISK.LUNG.BOOST",
        RuleType.RISK,
        RuleAction.BOOST,
        {"risk_code": "LUNG_RISK", "minimum_probability": 0.8, "score_delta": 0.01},
        priority=100,
    )
    block = make_rule(
        "AGE.BLOCK_UNDER_50",
        RuleType.AGE,
        RuleAction.BLOCK,
        {"allowed_min_age": 50},
        priority=1,
    )

    result = RuleEngine().evaluate(request, [boost, block])

    assert result.final_status is FinalRuleStatus.BLOCKED
    assert result.adjusted_score == 0.0
    assert result.rule_decisions[0].action is RuleAction.BLOCK


def test_same_action_is_ordered_by_priority_and_disabled_rule_never_executes() -> None:
    high = make_rule(
        "MISSING_DATA.HIGH",
        RuleType.MISSING_DATA,
        RuleAction.REVIEW_REQUIRED,
        {"required_fields": ["exam_history"]},
        priority=90,
    )
    low = make_rule(
        "MISSING_DATA.LOW",
        RuleType.MISSING_DATA,
        RuleAction.REVIEW_REQUIRED,
        {"required_fields": ["risk_predictions"]},
        priority=10,
    )
    disabled = make_rule(
        "MISSING_DATA.DISABLED",
        RuleType.MISSING_DATA,
        RuleAction.BLOCK,
        {"required_fields": ["exam_history"]},
        priority=999,
        enabled=False,
    )

    result = RuleEngine().evaluate(make_request(), [low, disabled, high])

    assert [decision.rule_code for decision in result.rule_decisions] == [
        "MISSING_DATA.HIGH",
        "MISSING_DATA.LOW",
    ]
    assert result.execution_trace[0].rule_code == "MISSING_DATA.DISABLED"
    assert result.execution_trace[0].enabled is False
    assert result.execution_trace[0].matched is False


def test_same_input_and_rule_version_produce_identical_json_trace() -> None:
    request = make_request()
    rule = make_rule(
        "MISSING_DATA.DETERMINISTIC",
        RuleType.MISSING_DATA,
        RuleAction.REVIEW_REQUIRED,
        {"required_fields": ["exam_history"]},
        version="rules-2026.03",
    )
    engine = RuleEngine()

    first = engine.evaluate(request, [rule])
    second = engine.evaluate(request, [rule])

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.rule_decisions[0].version == "rules-2026.03"
    assert first.rule_set_version.startswith("sha256:")


def test_execution_trace_shows_score_adjustment_then_manual_review() -> None:
    request = make_request(
        exam_history=[
            ExamHistoryFact(
                exam_item_id="exam-item-ct",
                exam_code="CHEST_CT",
                performed_at=date(2026, 1, 1),
                result_status="completed",
                body_part="CHEST",
                radiation=True,
            )
        ]
    )
    interval_reduce = make_rule(
        "INTERVAL.REDUCE",
        RuleType.INTERVAL,
        RuleAction.REDUCE,
        {"minimum_months": 12, "score_delta": 0.2},
        priority=90,
    )
    radiation_review = make_rule(
        "RADIATION.REVIEW",
        RuleType.RADIATION,
        RuleAction.REVIEW_REQUIRED,
        {"lookback_months": 6, "same_body_part": True},
        priority=80,
    )

    result = RuleEngine().evaluate(request, [radiation_review, interval_reduce])

    assert result.deepfm_score == 0.91
    assert result.adjusted_score == 0.71
    assert result.final_status is FinalRuleStatus.REVIEW_REQUIRED
    assert [record.action for record in result.execution_trace] == [
        RuleAction.REDUCE,
        RuleAction.REVIEW_REQUIRED,
    ]


def test_invalid_enabled_rule_configuration_fails_safe_to_manual_review() -> None:
    invalid = make_rule(
        "RADIATION.INVALID.CONFIG",
        RuleType.RADIATION,
        RuleAction.DEFER,
        {"same_body_part": True},
    )

    result = RuleEngine().evaluate(make_request(), [invalid])

    assert result.final_status is FinalRuleStatus.REVIEW_REQUIRED
    assert result.rule_decisions[0].action is RuleAction.REVIEW_REQUIRED
    assert "配置无效" in result.rule_decisions[0].reason
    assert result.execution_trace[0].matched is True
