export type RuleType =
  | "INTERVAL"
  | "DUPLICATE"
  | "RADIATION"
  | "AGE"
  | "GENDER"
  | "RISK"
  | "LESION_FOLLOWUP"
  | "MISSING_DATA";

export type RuleAction =
  | "ALLOW"
  | "BOOST"
  | "REDUCE"
  | "DEFER"
  | "BLOCK"
  | "REVIEW_REQUIRED";

export type FinalRuleStatus = "ALLOWED" | "DEFERRED" | "BLOCKED" | "REVIEW_REQUIRED";

export type RuleDecision = {
  rule_code: string;
  rule_type: RuleType;
  action: RuleAction;
  reason: string;
  source: string;
  version: string;
  priority: number;
  score_delta: number;
  evidence_refs: string[];
};

export type RuleExecutionRecord = {
  rule_code: string;
  version: string;
  priority: number;
  enabled: boolean;
  matched: boolean;
  action: RuleAction | null;
  reason: string;
  score_before: number;
  score_after: number;
};

export type RuleEvaluationResult = {
  trace_id: string;
  deepfm_score: number;
  adjusted_score: number;
  final_status: FinalRuleStatus;
  rule_decisions: RuleDecision[];
  execution_trace: RuleExecutionRecord[];
  rule_set_version: string;
  is_demo?: boolean;
};
