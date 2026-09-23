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
    # 同一检查（空腹血糖 1558-6）被同组两条规则推荐 → 只计一次，只保留胜者依据
    assert codes.count("1558-6") == 1
    assert "4548-4" in codes
    glu = next(c for c in result.candidates if c.exam_code == "1558-6")
    assert {b.rule_code for b in glu.bases} == {"RU-GLU-RECHECK"}, "冲突组败者依据必须移除"
    assert all("7.2" in r for r in glu.reasons)
    # 败者留痕可追踪
    assert any(
        e.kind == "conflict_group" and e.rule_code == "RU-GLU-IFG-RECHECK"
        for e in result.excluded
    )


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


# ---- 冲突组败者必须真正退出候选（PR #24 P1） ----


def conflict_rule(
    code: str,
    priority: int,
    exams: tuple[str, ...],
    condition: str,
    *,
    group: str = "G-TEST",
    version: str = "1.0",
) -> "RuleContentItem":
    from app.rule_candidates import RuleContentItem

    return RuleContentItem(
        rule_code=code,
        version=version,
        priority=priority,
        applies_to_condition=condition,
        trigger_directions=("high",),
        recommended_exam_codes=exams,
        reason_template=f"{code} 触发（{{value}}）",
        source="测试",
        source_version="1.0",
        status="enabled",
        conflict_group=group,
    )


def test_conflict_group_loser_really_leaves_candidates() -> None:
    """审查复现：A/B 同组，A 推荐 EXAM_A、B 推荐 EXAM_B，B 必须退出 candidates。"""
    rules = [
        conflict_rule("RU-A", 10, ("EXAM_A",), "C1"),
        conflict_rule("RU-B", 20, ("EXAM_B",), "C2"),
    ]
    result = RuleCandidateService(rules).candidates(
        [
            finding("f1", "X1", "high", "C1", "条件一", "1"),
            finding("f2", "X2", "high", "C2", "条件二", "2"),
        ]
    )
    codes = [c.exam_code for c in result.candidates]
    assert codes == ["EXAM_A"], "败者推荐项目不得留在候选中"
    assert any(
        e.kind == "conflict_group" and e.rule_code == "RU-B" and e.exam_code == "EXAM_B"
        for e in result.excluded
    )


def test_conflict_group_shared_exam_keeps_loser_basis_out() -> None:
    """同组两规则推荐同一检查：检查保留（胜者依据），败者依据不进入。"""
    rules = [
        conflict_rule("RU-A", 10, ("EXAM_SHARED",), "C1"),
        conflict_rule("RU-B", 20, ("EXAM_SHARED",), "C2"),
    ]
    result = RuleCandidateService(rules).candidates(
        [
            finding("f1", "X1", "high", "C1", "条件一", "1"),
            finding("f2", "X2", "high", "C2", "条件二", "2"),
        ]
    )
    assert [c.exam_code for c in result.candidates] == ["EXAM_SHARED"]
    shared = result.candidates[0]
    assert {b.rule_code for b in shared.bases} == {"RU-A"}, "败者依据不得残留"
    assert shared.priority == 10, "优先级须按剩余依据重算"


def test_conflict_group_loser_exam_keeps_other_valid_rule_basis() -> None:
    """败者推荐项目若另有其他有效规则推荐，依据保留并重算优先级。"""
    rules = [
        conflict_rule("RU-A", 10, ("EXAM_A",), "C1"),
        conflict_rule("RU-B", 20, ("EXAM_A", "EXAM_B"), "C2"),
        conflict_rule("RU-C", 30, ("EXAM_B",), "C3", group="G-OTHER"),
    ]
    result = RuleCandidateService(rules).candidates(
        [
            finding("f1", "X1", "high", "C1", "条件一", "1"),
            finding("f2", "X2", "high", "C2", "条件二", "2"),
            finding("f3", "X3", "high", "C3", "条件三", "3"),
        ]
    )
    exam_b = next((c for c in result.candidates if c.exam_code == "EXAM_B"), None)
    assert exam_b is not None, "EXAM_B 仍有 RU-C 依据，应保留为候选"
    assert {b.rule_code for b in exam_b.bases} == {"RU-C"}
    assert exam_b.priority == 30, "优先级须从 20（败者）重算为 30（RU-C）"


def test_same_rule_from_multiple_findings_does_not_self_conflict() -> None:
    """同一规则被多个 finding 触发，不得与自身冲突。"""
    rules = [conflict_rule("RU-A", 10, ("EXAM_A",), "*", group="G-TEST")]
    result = RuleCandidateService(rules).candidates(
        [
            finding("f1", "X1", "high", "C1", "条件一", "1"),
            finding("f2", "X1", "high", "C1", "条件一", "1", "rec-2"),
        ]
    )
    assert [c.exam_code for c in result.candidates] == ["EXAM_A"]
    assert len(result.candidates[0].bases) == 2
    assert not [e for e in result.excluded if e.kind == "conflict_group"]


# ---- 年龄适用性：缺失即待确认（PR #24 P1） ----


def age_rule(code: str, min_age: int | None, max_age: int | None) -> "RuleContentItem":
    from app.rule_candidates import RuleContentItem

    return RuleContentItem(
        rule_code=code,
        version="1.0",
        priority=10,
        applies_to_condition="C1",
        trigger_directions=("high",),
        recommended_exam_codes=(f"EXAM-{code}",),
        reason_template=f"{code} 触发",
        source="测试",
        source_version="1.0",
        status="enabled",
        applies_min_age=min_age,
        applies_max_age=max_age,
    )


def test_age_limited_rule_not_executed_when_age_unknown() -> None:
    """审查复现：age=None + applies_min_age=50 不得产生候选。"""
    result = RuleCandidateService([age_rule("RU-AGE", 50, None)]).candidates(
        [finding("f1", "X1", "high", "C1", "条件一", "1")],
        PatientContext(sex=None, age=None),
    )
    assert result.candidates == []
    assert any(
        e.kind == "applicability" and e.rule_code == "RU-AGE" for e in result.excluded
    )
    assert any("年龄" in m.prompt for m in result.missing_info)


def test_age_limited_rule_applies_when_age_known_and_in_range() -> None:
    result = RuleCandidateService([age_rule("RU-AGE", 50, 70)]).candidates(
        [finding("f1", "X1", "high", "C1", "条件一", "1")],
        PatientContext(sex=None, age=60),
    )
    assert [c.exam_code for c in result.candidates] == ["EXAM-RU-AGE"]
    assert not [m for m in result.missing_info if "年龄" in m.prompt], "年龄已知不应提示缺失"


def test_age_limited_rule_excluded_when_age_out_of_range() -> None:
    result = RuleCandidateService([age_rule("RU-AGE", 50, 70)]).candidates(
        [finding("f1", "X1", "high", "C1", "条件一", "1")],
        PatientContext(sex=None, age=30),
    )
    assert result.candidates == []
    excluded = [e for e in result.excluded if e.rule_code == "RU-AGE"]
    assert excluded and "≥50 岁" in excluded[0].reason
    assert not [m for m in result.missing_info if "年龄" in m.prompt]


def test_rule_without_age_limit_needs_no_age() -> None:
    rule = age_rule("RU-NOAGE", None, None)
    result = RuleCandidateService([rule]).candidates(
        [finding("f1", "X1", "high", "C1", "条件一", "1")], PatientContext(age=None)
    )
    assert [c.exam_code for c in result.candidates] == ["EXAM-RU-NOAGE"]
    assert not [m for m in result.missing_info if "年龄" in m.prompt]


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
