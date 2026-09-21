"""H07 规则候选：触发、去重、排序、缺失信息与排除记录。"""

from datetime import date

import pytest

from app.rule_candidates import (
    CandidateResult,
    NormalizedFinding,
    PatientContext,
    RuleCandidateService,
    load_rule_content,
)


def finding(
    finding_id: str,
    exam_code: str,
    direction: str,
    condition_code: str,
    condition_name: str,
    value_text: str,
    record_ref: str = "rec-1",
) -> NormalizedFinding:
    return NormalizedFinding(
        finding_id=finding_id,
        exam_code=exam_code,
        direction=direction,
        condition_code=condition_code,
        condition_name=condition_name,
        value_text=value_text,
        record_ref=record_ref,
        observed_at=date(2026, 6, 1),
    )


@pytest.fixture()
def service() -> RuleCandidateService:
    return RuleCandidateService()


def test_builtin_rule_content_loads_draft_pending(service: RuleCandidateService) -> None:
    rules = load_rule_content()
    assert len(rules) >= 12
    for rule in rules:
        assert rule.status == "draft", rule.rule_code
        assert rule.review_status == "pending_review", rule.rule_code
        assert rule.source and rule.source_version, rule.rule_code


def test_draft_rules_excluded_by_default(service: RuleCandidateService) -> None:
    result = service.candidates(
        [finding("f1", "1558-6", "high", "E11.9", "2型糖尿病（待排查）", "7.2 mmol/L")]
    )
    assert result.candidates == []
    assert any(e.kind == "draft" for e in result.excluded)


def test_glucose_finding_generates_deduplicated_candidates(service: RuleCandidateService) -> None:
    result = service.candidates(
        [
            finding(
                "f1", "1558-6", "high", "E11.9", "2型糖尿病（待排查）", "7.2 mmol/L", "rec-glu"
            ),
            finding("f2", "1558-6", "high", "R73.0", "空腹血糖受损", "7.2 mmol/L", "rec-glu"),
        ],
        include_drafts=True,
    )
    codes = [c.exam_code for c in result.candidates]
    # 同一检查（空腹血糖 1558-6）触发两条规则 → 只计一次，依据合并
    assert codes.count("1558-6") == 1
    assert "4548-4" in codes
    glu = next(c for c in result.candidates if c.exam_code == "1558-6")
    assert {b.rule_code for b in glu.bases} == {"RU-GLU-RECHECK", "RU-GLU-IFG-RECHECK"}
    assert all("7.2" in r for r in glu.reasons)


def test_candidates_sorted_by_priority_then_code(service: RuleCandidateService) -> None:
    result = service.candidates(
        [
            finding("f1", "1558-6", "high", "E11.9", "DM", "7.2"),
            finding("f2", "8480-6", "high", "I10", "HTN", "148"),
            finding("f3", "2035-0", "high", "IC:C-TUMOR-MARKER-OBSERVE", "TMO", "12"),
        ],
        include_drafts=True,
    )
    priorities = [c.priority for c in result.candidates]
    assert priorities == sorted(priorities)
    assert result.version == "rule-candidates-v1"


def test_sex_applicable_rule_excluded_for_female(service: RuleCandidateService) -> None:
    cea = finding("f1", "2035-0", "high", "IC:C-TUMOR-MARKER-OBSERVE", "TMO", "12")
    male = service.candidates([cea], PatientContext(sex="male"), include_drafts=True)
    female = service.candidates([cea], PatientContext(sex="female"), include_drafts=True)
    assert "2857-1" in [c.exam_code for c in male.candidates]
    assert "2857-1" not in [c.exam_code for c in female.candidates]
    assert any(
        e.rule_code == "RU-TUMOR-MARKER-PSA" and e.kind == "applicability"
        for e in female.excluded
    )


def test_unknown_sex_produces_missing_info_not_silent(service: RuleCandidateService) -> None:
    cea = finding("f1", "2035-0", "high", "IC:C-TUMOR-MARKER-OBSERVE", "TMO", "12")
    result = service.candidates([cea], PatientContext(sex=None), include_drafts=True)
    assert "2857-1" not in [c.exam_code for c in result.candidates]
    assert any("性别" in m.prompt for m in result.missing_info)


def test_unknown_direction_prompts_recheck(service: RuleCandidateService) -> None:
    result = service.candidates(
        [finding("f1", "1558-6", "unknown", "E11.9", "DM", "待确认")],
        include_drafts=True,
    )
    assert result.candidates == []
    assert any("方向未知" in m.prompt for m in result.missing_info)


def test_missing_info_prompt_from_rule(service: RuleCandidateService) -> None:
    result = service.candidates(
        [
            finding(
                "f1",
                "IC:M-STOOL-OCCULT-BLOOD",
                "qualitative_positive",
                "IC:C-CRC-SCREEN",
                "筛查",
                "阳性",
            )
        ],
        include_drafts=True,
    )
    assert any("肠镜" in m.prompt for m in result.missing_info)


def test_conflict_group_keeps_higher_priority(service: RuleCandidateService) -> None:
    result = service.candidates(
        [
            finding("f1", "1558-6", "high", "E11.9", "DM", "7.2", "rec-a"),
            finding("f2", "1558-6", "high", "R73.0", "IFG", "6.5", "rec-b"),
        ],
        include_drafts=True,
    )
    loser_excluded = [
        e
        for e in result.excluded
        if e.kind == "conflict_group" and e.rule_code == "RU-GLU-IFG-RECHECK"
    ]
    assert loser_excluded, "冲突组败者应被排除并留痕"
    assert "保留更高优先级规则" in loser_excluded[0].reason


def test_deterministic_output_same_input(service: RuleCandidateService) -> None:
    findings = [
        finding("f1", "1558-6", "high", "E11.9", "DM", "7.2"),
        finding("f2", "8480-6", "high", "I10", "HTN", "148"),
    ]
    one = service.candidates(findings, include_drafts=True)
    two = service.candidates(list(reversed(findings)), include_drafts=True)
    assert one.as_dict() == two.as_dict()


def test_custom_rules_can_be_injected() -> None:
    from app.rule_candidates import RuleContentItem

    custom = RuleContentItem(
        rule_code="RU-TEST-001",
        version="1.0",
        priority=1,
        applies_to_condition="*",
        trigger_directions=("any",),
        recommended_exam_codes=("IC:EX-ECG",),
        reason_template="测试规则触发（{condition}）",
        source="测试",
        source_version="1.0",
        status="enabled",
    )
    result = RuleCandidateService([custom]).candidates(
        [finding("f1", "1558-6", "high", "E11.9", "DM", "7.2")]
    )
    assert [c.exam_code for c in result.candidates] == ["IC:EX-ECG"]
    assert result.candidates[0].bases[0].review_status == "pending_review"


def test_invalid_rule_content_rejected(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"entries": [{"rule_code": "RU-BAD", "version": "1.0", "priority": 1,'
        ' "applies_to_condition": "*", "trigger_directions": ["high"],'
        ' "recommended_exam_codes": ["X"], "reason_template": "r",'
        ' "source": "", "source_version": "1.0"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as excinfo:
        load_rule_content(bad)
    assert "缺少 source" in str(excinfo.value)


def test_reviewed_status_is_rejected_in_loader(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"entries": [{"rule_code": "RU-BAD", "version": "1.0", "priority": 1,'
        ' "applies_to_condition": "*", "trigger_directions": ["high"],'
        ' "recommended_exam_codes": ["X"], "reason_template": "r",'
        ' "source": "s", "source_version": "1.0", "review_status": "reviewed"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as excinfo:
        load_rule_content(bad)
    assert "医学审核" in str(excinfo.value)


def test_as_dict_shape(service: RuleCandidateService) -> None:
    result = service.candidates(
        [finding("f1", "1558-6", "high", "E11.9", "DM", "7.2")],
        PatientContext(sex="female", age=45),
        include_drafts=True,
    )
    payload = result.as_dict()
    assert isinstance(payload, CandidateResult.__mro__ and dict)
    assert payload["version"] == "rule-candidates-v1"
    assert all("bases" in c for c in payload["candidates"])
    assert payload["candidates"][0]["bases"][0]["review_status"] == "pending_review"
