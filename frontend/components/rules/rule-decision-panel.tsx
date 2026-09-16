import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { FinalRuleStatus, RuleAction, RuleEvaluationResult } from "@/types/rules";

const statusCopy: Record<FinalRuleStatus, { label: string; description: string }> = {
  ALLOWED: {
    label: "规则允许",
    description: "当前规则未阻断该候选项目；是否进入具体方案由后续方案生成模块决定。",
  },
  DEFERRED: {
    label: "建议延后",
    description: "项目命中了复查间隔或重复性约束，本次不应作为普通推荐处理。",
  },
  BLOCKED: {
    label: "已阻断",
    description: "项目命中安全阻断规则，模型高分不能覆盖该结果。",
  },
  REVIEW_REQUIRED: {
    label: "需要人工确认",
    description: "资料不足、规则冲突或安全条件需要由有资质的医务人员确认。",
  },
};

const actionCopy: Record<RuleAction, string> = {
  ALLOW: "允许",
  BOOST: "提高排序",
  REDUCE: "降低排序",
  DEFER: "延后",
  BLOCK: "阻断",
  REVIEW_REQUIRED: "人工确认",
};

type RuleDecisionPanelProps = {
  result: RuleEvaluationResult;
};

export function RuleDecisionPanel({ result }: RuleDecisionPanelProps) {
  const status = statusCopy[result.final_status];

  return (
    <section aria-label="医疗规则决策" className="space-y-4">
      <Card>
        <CardHeader className="border-b">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{status.label}</CardTitle>
              <CardDescription className="mt-1 max-w-2xl">{status.description}</CardDescription>
            </div>
            <div className="flex gap-2">
              {result.is_demo ? <Badge variant="destructive">DEMO DATA</Badge> : null}
              <Badge variant={result.final_status === "ALLOWED" ? "secondary" : "outline"}>
                {result.final_status}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">DeepFM 原始分数</p>
            <p className="mt-1 font-mono text-lg font-semibold">
              {result.deepfm_score.toFixed(3)}
            </p>
          </div>
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">规则调整后分数</p>
            <p className="mt-1 font-mono text-lg font-semibold">
              {result.adjusted_score.toFixed(3)}
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-3">
        {result.rule_decisions.length === 0 ? (
          <Card size="sm">
            <CardContent className="text-sm text-muted-foreground">
              当前没有命中的规则决定；该结果不等同于疾病诊断或最终体检方案。
            </CardContent>
          </Card>
        ) : (
          result.rule_decisions.map((decision) => (
            <Card key={`${decision.rule_code}@${decision.version}`} size="sm">
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle>{decision.rule_code}</CardTitle>
                  <Badge variant="outline">{actionCopy[decision.action]}</Badge>
                </div>
                <CardDescription>{decision.reason}</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                <p>来源：{decision.source}</p>
                <p>规则版本：{decision.version}</p>
                <p>优先级：{decision.priority}</p>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        Trace：{result.trace_id} · Rule Set：{result.rule_set_version}
      </p>
    </section>
  );
}
