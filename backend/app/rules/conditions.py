from dataclasses import dataclass
from datetime import date

from app.rules.models import MedicalRuleDefinition, RuleEvaluationRequest, RuleType


@dataclass(frozen=True)
class ConditionResult:
    matched: bool
    reason: str
    evidence_refs: tuple[str, ...] = ()


def _full_months_between(earlier: date, later: date) -> int:
    months = (later.year - earlier.year) * 12 + later.month - earlier.month
    if later.day < earlier.day:
        months -= 1
    return max(0, months)


class RuleConditionEvaluator:
    """Pure condition matcher. It never resolves conflicts or changes final status."""

    def evaluate(
        self, rule: MedicalRuleDefinition, request: RuleEvaluationRequest
    ) -> ConditionResult:
        if rule.exam_item_id is not None and rule.exam_item_id != request.exam_item.exam_item_id:
            return ConditionResult(False, "规则不适用于当前体检项目")
        if rule.rule_type is RuleType.INTERVAL:
            return self._evaluate_interval(rule, request)
        if rule.rule_type is RuleType.DUPLICATE:
            return self._evaluate_duplicate(rule, request)
        if rule.rule_type is RuleType.RADIATION:
            return self._evaluate_radiation(rule, request)
        if rule.rule_type is RuleType.AGE:
            return self._evaluate_age(rule, request)
        if rule.rule_type is RuleType.GENDER:
            return self._evaluate_gender(rule, request)
        if rule.rule_type is RuleType.RISK:
            return self._evaluate_risk(rule, request)
        if rule.rule_type is RuleType.LESION_FOLLOWUP:
            return self._evaluate_lesion_followup(rule, request)
        if rule.rule_type is RuleType.MISSING_DATA:
            return self._evaluate_missing_data(rule, request)
        raise ValueError(f"unsupported rule type: {rule.rule_type}")

    @staticmethod
    def _evaluate_interval(
        rule: MedicalRuleDefinition, request: RuleEvaluationRequest
    ) -> ConditionResult:
        configured = rule.condition.get("minimum_months")
        minimum_months = (
            int(configured)
            if isinstance(configured, int | float)
            else request.exam_item.recommended_interval_months
        )
        if minimum_months is None or minimum_months < 0:
            raise ValueError("INTERVAL rule requires a non-negative minimum_months")

        matching_history = [
            history
            for history in request.exam_history
            if history.exam_item_id == request.exam_item.exam_item_id
            or history.exam_code == request.exam_item.code
        ]
        if not matching_history:
            return ConditionResult(False, "没有同项目既往检查记录")

        latest = max(matching_history, key=lambda item: item.performed_at)
        elapsed_months = _full_months_between(latest.performed_at, request.patient.as_of_date)
        if elapsed_months >= minimum_months:
            return ConditionResult(
                False,
                f"距上次同项目检查 {elapsed_months} 个月，已达到最小间隔 {minimum_months} 个月",
            )
        return ConditionResult(
            True,
            f"距上次同项目检查仅 {elapsed_months} 个月，未达到最小间隔 {minimum_months} 个月",
            tuple(latest.evidence_refs),
        )

    @staticmethod
    def _evaluate_duplicate(
        rule: MedicalRuleDefinition, request: RuleEvaluationRequest
    ) -> ConditionResult:
        raw_minimum = rule.condition.get("minimum_overlap_count", 1)
        if not isinstance(raw_minimum, int) or raw_minimum < 1:
            raise ValueError("DUPLICATE rule requires a positive minimum_overlap_count")
        candidate_groups = set(request.exam_item.functional_groups)
        if not candidate_groups:
            return ConditionResult(False, "当前项目未配置功能分组，无法判定重复")

        for selected in request.selected_exam_items:
            overlap = sorted(candidate_groups.intersection(selected.functional_groups))
            if len(overlap) >= raw_minimum:
                return ConditionResult(
                    True,
                    f"与已选项目“{selected.name}”存在功能重叠：{', '.join(overlap)}",
                )
        return ConditionResult(False, "未发现达到阈值的功能重叠项目")

    @staticmethod
    def _evaluate_radiation(
        rule: MedicalRuleDefinition, request: RuleEvaluationRequest
    ) -> ConditionResult:
        if not request.exam_item.radiation:
            return ConditionResult(False, "当前项目不具有辐射属性")
        raw_lookback = rule.condition.get("lookback_months")
        if not isinstance(raw_lookback, int | float) or raw_lookback < 0:
            raise ValueError("RADIATION rule requires a non-negative lookback_months")
        same_body_part = rule.condition.get("same_body_part", True)
        if not isinstance(same_body_part, bool):
            raise ValueError("RADIATION condition.same_body_part must be boolean")

        related = []
        for history in request.exam_history:
            if not history.radiation:
                continue
            if same_body_part and (
                request.exam_item.body_part is None
                or history.body_part != request.exam_item.body_part
            ):
                continue
            elapsed = _full_months_between(history.performed_at, request.patient.as_of_date)
            if elapsed <= int(raw_lookback):
                related.append((history, elapsed))
        if not related:
            return ConditionResult(False, "回溯期内未发现相关辐射检查")

        latest, elapsed = min(related, key=lambda pair: pair[1])
        return ConditionResult(
            True,
            f"{elapsed} 个月内已有相关辐射检查 {latest.exam_code}",
            tuple(latest.evidence_refs),
        )

    @staticmethod
    def _evaluate_age(
        rule: MedicalRuleDefinition, request: RuleEvaluationRequest
    ) -> ConditionResult:
        age = request.patient.age
        if age is None:
            return ConditionResult(False, "年龄资料缺失；应由 MISSING_DATA 规则处理")
        minimum = rule.condition.get("allowed_min_age")
        maximum = rule.condition.get("allowed_max_age")
        if minimum is None and maximum is None:
            raise ValueError("AGE rule requires allowed_min_age or allowed_max_age")
        if minimum is not None and (not isinstance(minimum, int) or minimum < 0):
            raise ValueError("AGE condition.allowed_min_age must be a non-negative integer")
        if maximum is not None and (not isinstance(maximum, int) or maximum < 0):
            raise ValueError("AGE condition.allowed_max_age must be a non-negative integer")
        if minimum is not None and age < minimum:
            return ConditionResult(True, f"当前年龄 {age} 岁，低于规则适用下限 {minimum} 岁")
        if maximum is not None and age > maximum:
            return ConditionResult(True, f"当前年龄 {age} 岁，高于规则适用上限 {maximum} 岁")
        return ConditionResult(False, f"当前年龄 {age} 岁处于规则适用范围")

    @staticmethod
    def _evaluate_gender(
        rule: MedicalRuleDefinition, request: RuleEvaluationRequest
    ) -> ConditionResult:
        allowed = rule.condition.get("allowed_genders")
        if not isinstance(allowed, list) or not allowed or not all(
            isinstance(value, str) for value in allowed
        ):
            raise ValueError("GENDER rule requires a non-empty allowed_genders list")
        if request.patient.sex == "unknown":
            return ConditionResult(False, "性别资料缺失；应由 MISSING_DATA 规则处理")
        if request.patient.sex not in allowed:
            return ConditionResult(
                True,
                f"当前性别为 {request.patient.sex}，不在规则适用人群 {', '.join(allowed)} 中",
            )
        return ConditionResult(False, "当前性别符合规则适用人群")

    @staticmethod
    def _evaluate_risk(
        rule: MedicalRuleDefinition, request: RuleEvaluationRequest
    ) -> ConditionResult:
        risk_code = rule.condition.get("risk_code")
        minimum = rule.condition.get("minimum_probability", 0.0)
        maximum = rule.condition.get("maximum_probability", 1.0)
        if not isinstance(risk_code, str) or not risk_code:
            raise ValueError("RISK rule requires risk_code")
        if not isinstance(minimum, int | float) or not 0 <= minimum <= 1:
            raise ValueError("RISK minimum_probability must be within [0, 1]")
        if not isinstance(maximum, int | float) or not 0 <= maximum <= 1:
            raise ValueError("RISK maximum_probability must be within [0, 1]")

        risk = next(
            (item for item in request.risk_predictions if item.risk_code == risk_code),
            None,
        )
        if risk is None:
            return ConditionResult(False, f"未提供风险项 {risk_code}")
        if float(minimum) <= risk.probability <= float(maximum):
            return ConditionResult(
                True,
                f"风险项 {risk_code} 概率 {risk.probability:.3f} 命中规则区间",
                tuple(risk.evidence_refs),
            )
        return ConditionResult(False, f"风险项 {risk_code} 未命中规则概率区间")

    @staticmethod
    def _evaluate_lesion_followup(
        rule: MedicalRuleDefinition, request: RuleEvaluationRequest
    ) -> ConditionResult:
        lesion_type = rule.condition.get("lesion_type")
        location = rule.condition.get("location")
        growing = rule.condition.get("growing")
        if lesion_type is not None and not isinstance(lesion_type, str):
            raise ValueError("LESION_FOLLOWUP lesion_type must be a string")
        if location is not None and not isinstance(location, str):
            raise ValueError("LESION_FOLLOWUP location must be a string")
        if growing is not None and not isinstance(growing, bool):
            raise ValueError("LESION_FOLLOWUP growing must be boolean")
        if lesion_type is None and location is None and growing is None:
            raise ValueError("LESION_FOLLOWUP requires at least one lesion condition")

        for lesion in request.lesion_history:
            if lesion_type is not None and lesion.lesion_type != lesion_type:
                continue
            if location is not None and lesion.location != location:
                continue
            if growing is not None and lesion.growing is not growing:
                continue
            return ConditionResult(
                True,
                f"病灶 {lesion.lesion_type} 的纵向状态命中随访规则",
                tuple(lesion.evidence_refs),
            )
        return ConditionResult(False, "未发现命中随访条件的结构化病灶记录")

    @staticmethod
    def _evaluate_missing_data(
        rule: MedicalRuleDefinition, request: RuleEvaluationRequest
    ) -> ConditionResult:
        required = rule.condition.get("required_fields")
        if not isinstance(required, list) or not required or not all(
            isinstance(field, str) for field in required
        ):
            raise ValueError("MISSING_DATA rule requires a non-empty required_fields list")

        missing: list[str] = []
        for field in required:
            if field == "age" and request.patient.age is None:
                missing.append(field)
            elif field == "gender" and request.patient.sex == "unknown":
                missing.append(field)
            elif field == "exam_history" and not request.exam_history:
                missing.append(field)
            elif field == "risk_predictions" and not request.risk_predictions:
                missing.append(field)
            elif field == "lesion_history" and not request.lesion_history:
                missing.append(field)
            elif field.startswith("normalized_facts."):
                fact_name = field.partition(".")[2]
                if request.patient.normalized_facts.get(fact_name) is None:
                    missing.append(field)
        if missing:
            return ConditionResult(True, f"缺少规则所需关键资料：{', '.join(missing)}")
        return ConditionResult(False, "规则所需关键资料完整")
