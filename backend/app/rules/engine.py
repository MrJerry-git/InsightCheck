from collections.abc import Sequence
from hashlib import sha256

from app.rules.conditions import RuleConditionEvaluator
from app.rules.models import (
    FinalRuleStatus,
    MedicalRuleDefinition,
    RuleAction,
    RuleDecision,
    RuleEvaluationRequest,
    RuleEvaluationResult,
    RuleExecutionRecord,
)

_ACTION_PRECEDENCE = {
    RuleAction.BLOCK: 60,
    RuleAction.REVIEW_REQUIRED: 50,
    RuleAction.DEFER: 40,
    RuleAction.REDUCE: 30,
    RuleAction.BOOST: 20,
    RuleAction.ALLOW: 10,
}


class RuleEngine:
    """Authoritative deterministic rule conflict resolver and execution trace producer."""

    def __init__(self, evaluator: RuleConditionEvaluator | None = None) -> None:
        self._evaluator = evaluator or RuleConditionEvaluator()

    def evaluate(
        self,
        request: RuleEvaluationRequest,
        rules: Sequence[MedicalRuleDefinition],
    ) -> RuleEvaluationResult:
        ordered_rules = sorted(
            rules,
            key=lambda rule: (-rule.priority, rule.rule_code, rule.version),
        )
        decisions: list[RuleDecision] = []
        trace: list[RuleExecutionRecord] = []
        score = request.deepfm_score

        for rule in ordered_rules:
            score_before = score
            if not rule.enabled:
                trace.append(
                    RuleExecutionRecord(
                        rule_code=rule.rule_code,
                        version=rule.version,
                        priority=rule.priority,
                        enabled=False,
                        matched=False,
                        reason="规则已禁用，未执行",
                        score_before=score,
                        score_after=score,
                    )
                )
                continue

            try:
                condition = self._evaluator.evaluate(rule, request)
            except (TypeError, ValueError) as exc:
                reason = f"规则配置无效，不能自动判定，需人工确认：{exc}"
                decisions.append(
                    RuleDecision(
                        rule_code=rule.rule_code,
                        rule_type=rule.rule_type,
                        action=RuleAction.REVIEW_REQUIRED,
                        reason=reason,
                        source=rule.source,
                        version=rule.version,
                        priority=rule.priority,
                    )
                )
                trace.append(
                    RuleExecutionRecord(
                        rule_code=rule.rule_code,
                        version=rule.version,
                        priority=rule.priority,
                        enabled=True,
                        matched=True,
                        action=RuleAction.REVIEW_REQUIRED,
                        reason=reason,
                        score_before=score,
                        score_after=score,
                    )
                )
                continue
            score_delta = self._score_delta(rule) if condition.matched else 0.0
            score = min(1.0, max(0.0, score + score_delta))
            if condition.matched:
                decisions.append(
                    RuleDecision(
                        rule_code=rule.rule_code,
                        rule_type=rule.rule_type,
                        action=rule.action,
                        reason=condition.reason,
                        source=rule.source,
                        version=rule.version,
                        priority=rule.priority,
                        score_delta=score_delta,
                        evidence_refs=list(condition.evidence_refs),
                    )
                )
            trace.append(
                RuleExecutionRecord(
                    rule_code=rule.rule_code,
                    version=rule.version,
                    priority=rule.priority,
                    enabled=True,
                    matched=condition.matched,
                    action=rule.action if condition.matched else None,
                    reason=condition.reason,
                    score_before=score_before,
                    score_after=score,
                )
            )

        decisions.sort(
            key=lambda item: (-_ACTION_PRECEDENCE[item.action], -item.priority, item.rule_code)
        )
        final_status = self._resolve_status(decisions)
        if final_status is FinalRuleStatus.BLOCKED:
            score = 0.0

        return RuleEvaluationResult(
            trace_id=request.trace_id,
            deepfm_score=request.deepfm_score,
            adjusted_score=score,
            final_status=final_status,
            rule_decisions=decisions,
            execution_trace=trace,
            rule_set_version=self._rule_set_version(rules),
        )

    @staticmethod
    def _score_delta(rule: MedicalRuleDefinition) -> float:
        magnitude = float(rule.condition.get("score_delta", 0.0))
        if rule.action is RuleAction.BOOST:
            return magnitude
        if rule.action is RuleAction.REDUCE:
            return -magnitude
        return 0.0

    @staticmethod
    def _resolve_status(decisions: Sequence[RuleDecision]) -> FinalRuleStatus:
        actions = {decision.action for decision in decisions}
        if RuleAction.BLOCK in actions:
            return FinalRuleStatus.BLOCKED
        if RuleAction.REVIEW_REQUIRED in actions:
            return FinalRuleStatus.REVIEW_REQUIRED
        if RuleAction.DEFER in actions:
            return FinalRuleStatus.DEFERRED
        return FinalRuleStatus.ALLOWED

    @staticmethod
    def _rule_set_version(rules: Sequence[MedicalRuleDefinition]) -> str:
        identity = "|".join(
            f"{rule.rule_code}@{rule.version}:{int(rule.enabled)}"
            for rule in sorted(rules, key=lambda item: (item.rule_code, item.version))
        )
        return f"sha256:{sha256(identity.encode('utf-8')).hexdigest()[:16]}"
