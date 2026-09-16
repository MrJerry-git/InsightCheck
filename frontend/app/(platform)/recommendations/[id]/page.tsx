import { RuleDecisionPanel } from "@/components/rules/rule-decision-panel";
import { MedicalDisclaimer } from "@/components/shared/medical-disclaimer";
import type { RuleEvaluationResult } from "@/types/rules";

const demoRuleResult: RuleEvaluationResult = {
  trace_id: "DEMO-rule-trace-2026",
  deepfm_score: 0.91,
  adjusted_score: 0.71,
  final_status: "REVIEW_REQUIRED",
  rule_set_version: "sha256:demo-rule-set",
  is_demo: true,
  rule_decisions: [
    {
      rule_code: "INTERVAL.CHEST_CT.DEMO",
      rule_type: "INTERVAL",
      action: "REDUCE",
      reason: "仅用于演示：距上次同项目检查 2 个月，未达到演示规则的 12 个月间隔。",
      source: "演示规则：产品交互验证，不作为临床指南",
      version: "demo-rule-v1",
      priority: 90,
      score_delta: -0.2,
      evidence_refs: ["DEMO-exam-history-2026-01"],
    },
    {
      rule_code: "RADIATION.CHEST.REVIEW.DEMO",
      rule_type: "RADIATION",
      action: "REVIEW_REQUIRED",
      reason: "仅用于演示：近期存在相关辐射检查记录，需要人工确认。",
      source: "演示规则：产品交互验证，不作为临床指南",
      version: "demo-rule-v1",
      priority: 80,
      score_delta: 0,
      evidence_refs: ["DEMO-exam-history-2026-01"],
    },
  ],
  execution_trace: [],
};

export default function RecommendationDetailPage() {
  return (
    <section className="space-y-6">
      <div className="space-y-2">
        <p className="text-sm font-semibold text-primary">循影定检 · 第七阶段</p>
        <h1 className="text-3xl font-bold tracking-tight">推荐规则说明</h1>
        <p className="max-w-3xl text-muted-foreground">
          展示后端规则引擎返回的推荐依据、延后原因和人工确认原因；页面不执行医疗规则。
        </p>
      </div>
      <RuleDecisionPanel result={demoRuleResult} />
      <MedicalDisclaimer />
    </section>
  );
}
