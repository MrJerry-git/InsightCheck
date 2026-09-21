"""规则候选服务的编排逻辑。"""

from __future__ import annotations

import json
from pathlib import Path

from app.rule_candidates.schemas import (
    Candidate,
    CandidateBase,
    CandidateResult,
    ExcludedItem,
    MissingInfoItem,
    NormalizedFinding,
    PatientContext,
    RuleContentItem,
)

DATA_DIR = Path(__file__).parent / "data"
SERVICE_VERSION = "rule-candidates-v1"


def load_rule_content(path: Path | None = None) -> list[RuleContentItem]:
    """加载规则内容文件；校验字段完整与状态合法。"""
    target = path or DATA_DIR / "rule_content.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    rules: list[RuleContentItem] = []
    problems: list[str] = []
    for index, raw in enumerate(payload["entries"]):
        where = f"{target.name}[{index}:{raw.get('rule_code', '?')}]"
        for field in ("rule_code", "version", "reason_template", "source", "source_version"):
            if not str(raw.get(field, "")).strip():
                problems.append(f"{where}: 缺少 {field}")
        if raw.get("status", "draft") not in ("draft", "enabled"):
            problems.append(f"{where}: 非法 status {raw.get('status')!r}")
        if raw.get("review_status", "pending_review") != "pending_review":
            problems.append(f"{where}: 首批规则不得宣称医学审核通过")
        rules.append(
            RuleContentItem(
                rule_code=raw["rule_code"],
                version=raw["version"],
                priority=int(raw["priority"]),
                applies_to_condition=raw["applies_to_condition"],
                trigger_directions=tuple(raw["trigger_directions"]),
                recommended_exam_codes=tuple(raw["recommended_exam_codes"]),
                reason_template=raw["reason_template"],
                source=raw["source"],
                source_version=raw["source_version"],
                review_status=raw.get("review_status", "pending_review"),
                status=raw.get("status", "draft"),
                applies_sex=raw.get("applies_sex"),
                applies_min_age=raw.get("applies_min_age"),
                applies_max_age=raw.get("applies_max_age"),
                conflict_group=raw.get("conflict_group"),
                missing_info_prompt=raw.get("missing_info_prompt"),
            )
        )
    if problems:
        raise ValueError("\n".join(problems))
    return rules


class _Accumulator:
    """一次运行的中间状态：候选依据、优先级、冲突命中。"""

    def __init__(self) -> None:
        self.bases: dict[str, list[CandidateBase]] = {}
        self.priority: dict[str, int] = {}
        self.conflict_hits: dict[str, list[RuleContentItem]] = {}

    def add(self, rule: RuleContentItem, finding: NormalizedFinding) -> None:
        for exam_code in rule.recommended_exam_codes:
            self.bases.setdefault(exam_code, []).append(
                CandidateBase(
                    rule_code=rule.rule_code,
                    rule_version=rule.version,
                    finding_id=finding.finding_id,
                    condition_code=finding.condition_code,
                    condition_name=finding.condition_name,
                    reason=rule.reason_template.format(
                        condition=finding.condition_name,
                        value=finding.value_text,
                        exam=finding.exam_code,
                    ),
                    source=rule.source,
                    source_version=rule.source_version,
                    review_status=rule.review_status,
                )
            )
            current = self.priority.get(exam_code)
            if current is None or rule.priority < current:
                self.priority[exam_code] = rule.priority
        if rule.conflict_group:
            self.conflict_hits.setdefault(rule.conflict_group, []).append(rule)

    def hit_exam_codes(self, rule: RuleContentItem) -> list[str]:
        return [c for c in rule.recommended_exam_codes if c in self.bases]


class RuleCandidateService:
    """H07 规则候选生成与确定性排序。"""

    VERSION = SERVICE_VERSION

    def __init__(self, rules: list[RuleContentItem] | None = None) -> None:
        self._rules = rules if rules is not None else load_rule_content()

    def candidates(
        self,
        findings: list[NormalizedFinding],
        patient: PatientContext | None = None,
        *,
        include_drafts: bool = False,
    ) -> CandidateResult:
        context = patient or PatientContext()
        result = CandidateResult(version=self.VERSION)
        active_rules = [
            rule
            for rule in self._rules
            if rule.status == "enabled" or (include_drafts and rule.status == "draft")
        ]
        excluded_rules = [
            rule
            for rule in self._rules
            if rule not in active_rules
        ]
        for rule in excluded_rules:
            for exam_code in rule.recommended_exam_codes:
                result.excluded.append(
                    ExcludedItem(
                        exam_code=exam_code,
                        rule_code=rule.rule_code,
                        reason="规则为草稿状态，未经启用不参与候选",
                        kind="draft",
                    )
                )

        accumulator = _Accumulator()
        for rule in sorted(active_rules, key=lambda r: (r.priority, r.rule_code, r.version)):
            problem, missing = self._applicability_problem(rule, context)
            if missing:
                result.missing_info.append(missing)
            if problem:
                for exam_code in rule.recommended_exam_codes:
                    result.excluded.append(
                        ExcludedItem(
                            exam_code=exam_code,
                            rule_code=rule.rule_code,
                            reason=problem,
                            kind="applicability",
                        )
                    )
                continue

            triggered = False
            for finding in findings:
                if self._rule_matches_finding(rule, finding):
                    triggered = True
                    accumulator.add(rule, finding)

            if triggered and rule.missing_info_prompt:
                result.missing_info.append(
                    MissingInfoItem(
                        prompt=rule.missing_info_prompt,
                        related_code=rule.rule_code,
                        reason="规则触发但所需项目/信息未登记",
                    )
                )

        # 发现方向未知 → 缺失信息提示
        for finding in findings:
            if finding.direction == "unknown":
                result.missing_info.append(
                    MissingInfoItem(
                        prompt=f"发现 {finding.exam_code} 方向未知，请复查以明确异常方向",
                        related_code=finding.exam_code,
                        reason="direction unknown",
                    )
                )

        # 冲突组裁决：同组规则同时触发时保留最高优先级，其余排除
        for group, triggered_rules in sorted(accumulator.conflict_hits.items()):
            if len(triggered_rules) < 2:
                continue
            ordered = sorted(triggered_rules, key=lambda r: (r.priority, r.rule_code))
            winner = ordered[0]
            for loser in ordered[1:]:
                for exam_code in loser.recommended_exam_codes:
                    result.excluded.append(
                        ExcludedItem(
                            exam_code=exam_code,
                            rule_code=loser.rule_code,
                            reason=(
                                f"冲突组 {group}：与 {winner.rule_code} 同时触发，"
                                "保留更高优先级规则"
                            ),
                            kind="conflict_group",
                        )
                    )

        # exam 级去重：同一检查只保留一个候选，依据合并（同检查多问题只计一次）
        result.candidates = [
            Candidate(
                exam_code=exam_code,
                priority=accumulator.priority[exam_code],
                bases=self._dedup_bases(bases),
            )
            for exam_code, bases in sorted(accumulator.bases.items())
        ]
        result.candidates.sort(key=lambda c: (c.priority, c.exam_code))
        result.missing_info.sort(key=lambda m: (m.related_code, m.prompt))
        result.excluded.sort(key=lambda e: (e.rule_code, e.exam_code, e.kind))
        return result

    @staticmethod
    def _dedup_bases(bases: list[CandidateBase]) -> list[CandidateBase]:
        seen: set[tuple[str, str, str, str]] = set()
        unique: list[CandidateBase] = []
        for base in bases:
            key = (base.rule_code, base.rule_version, base.finding_id, base.condition_code)
            if key in seen:
                continue
            seen.add(key)
            unique.append(base)
        return unique

    # ---- 匹配与适用性 ----

    @staticmethod
    def _rule_matches_finding(
        rule: RuleContentItem, finding: NormalizedFinding
    ) -> bool:
        if rule.applies_to_condition not in ("*", finding.condition_code):
            return False
        if finding.direction == "unknown":
            return False
        return finding.direction in rule.trigger_directions or "any" in rule.trigger_directions

    @staticmethod
    def _applicability_problem(
        rule: RuleContentItem, context: PatientContext
    ) -> tuple[str | None, MissingInfoItem | None]:
        if rule.applies_sex and context.sex is None:
            return (
                "性别缺失，无法判断适用性",
                MissingInfoItem(
                    prompt=f"规则 {rule.rule_code} 需要性别信息才能判断适用性",
                    related_code=rule.rule_code,
                    reason="patient sex unknown",
                ),
            )
        if rule.applies_sex and context.sex != rule.applies_sex:
            return (f"规则仅适用于 {'男性' if rule.applies_sex == 'male' else '女性'}", None)
        if context.age is not None:
            if rule.applies_min_age is not None and context.age < rule.applies_min_age:
                return (f"规则仅适用于 ≥{rule.applies_min_age} 岁", None)
            if rule.applies_max_age is not None and context.age > rule.applies_max_age:
                return (f"规则仅适用于 ≤{rule.applies_max_age} 岁", None)
        if rule.applies_min_age is not None or rule.applies_max_age is not None:
            return (
                None,
                MissingInfoItem(
                    prompt=f"规则 {rule.rule_code} 需要年龄信息才能判断适用性",
                    related_code=rule.rule_code,
                    reason="patient age unknown",
                ),
            )
        return None, None
