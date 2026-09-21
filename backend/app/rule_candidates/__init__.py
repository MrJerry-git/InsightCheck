"""规则内容、候选生成与确定性排序（H07）。

纯计算模块：输入是标准化发现（来自 H05 汇总与 H02 关联，由 T05 编排
构造）与患者上下文，输出确定性的检查候选、缺失信息提示与排除记录。
- 首批规则内容存于 data/rule_content.json，全部 status=draft、
  review_status=pending_review：未经医学审核的规则不默认启用；
- 本服务不是 DeepFM 已接入：排序是确定性的规则排序，DeepFM 走
  app/ml/recommendation 既有制品链路；
- 同一检查涉及多问题时只计一次（exam 级去重，理由合并）。
契约说明见 docs/H_SERIES_SERVICE_CONTRACTS.md 第八节。
"""

from app.rule_candidates.schemas import (
    FINDING_DIRECTIONS,
    RULE_STATUSES,
    Candidate,
    CandidateBase,
    CandidateResult,
    ExcludedItem,
    MissingInfoItem,
    NormalizedFinding,
    PatientContext,
    RuleContentItem,
)
from app.rule_candidates.service import RuleCandidateService, load_rule_content

__all__ = [
    "FINDING_DIRECTIONS",
    "RULE_STATUSES",
    "Candidate",
    "CandidateBase",
    "CandidateResult",
    "ExcludedItem",
    "MissingInfoItem",
    "NormalizedFinding",
    "PatientContext",
    "RuleCandidateService",
    "RuleContentItem",
    "load_rule_content",
]
