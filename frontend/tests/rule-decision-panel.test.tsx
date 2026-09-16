import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RuleDecisionPanel } from "../components/rules/rule-decision-panel";
import type { RuleEvaluationResult } from "../types/rules";

describe("RuleDecisionPanel", () => {
  it("renders manual-review reason, source, version, and score trace from backend output", () => {
    const result: RuleEvaluationResult = {
      trace_id: "trace-ui-demo",
      deepfm_score: 0.91,
      adjusted_score: 0.71,
      final_status: "REVIEW_REQUIRED",
      rule_set_version: "sha256:demo1234",
      is_demo: true,
      rule_decisions: [
        {
          rule_code: "RADIATION.REVIEW",
          rule_type: "RADIATION",
          action: "REVIEW_REQUIRED",
          reason: "近期已有相关辐射检查，需人工确认",
          source: "演示规则：前端渲染测试",
          version: "demo-rule-v1",
          priority: 80,
          score_delta: 0,
          evidence_refs: [],
        },
      ],
      execution_trace: [],
    };

    const markup = renderToStaticMarkup(<RuleDecisionPanel result={result} />);

    expect(markup).toContain("需要人工确认");
    expect(markup).toContain("近期已有相关辐射检查，需人工确认");
    expect(markup).toContain("演示规则：前端渲染测试");
    expect(markup).toContain("demo-rule-v1");
    expect(markup).toContain("0.910");
    expect(markup).toContain("0.710");
    expect(markup).toContain("DEMO DATA");
  });
});
