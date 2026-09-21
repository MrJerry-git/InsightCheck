"""规则候选的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

FINDING_DIRECTIONS = (
    "high",
    "low",
    "any",
    "qualitative_positive",
    "text_contains",
    "unknown",
)
RULE_STATUSES = ("draft", "enabled")


@dataclass(frozen=True)
class PatientContext:
    """患者上下文：用于规则适用性判断；缺失即为缺失，不猜测。"""

    sex: str | None = None  # "male" | "female" | None
    age: int | None = None


@dataclass(frozen=True)
class NormalizedFinding:
    """一条标准化发现（来自 H05 汇总 + H02 关联目录）。"""

    finding_id: str
    exam_code: str
    direction: str
    condition_code: str
    condition_name: str
    value_text: str
    record_ref: str
    observed_at: date | None = None

    def __post_init__(self) -> None:
        if self.direction not in FINDING_DIRECTIONS:
            raise ValueError(f"非法发现方向：{self.direction}")


@dataclass(frozen=True)
class RuleContentItem:
    """一条规则内容：依据/版本/适用条件齐备。"""

    rule_code: str
    version: str
    priority: int
    applies_to_condition: str  # condition_code 或 "*"
    trigger_directions: tuple[str, ...]
    recommended_exam_codes: tuple[str, ...]
    reason_template: str
    source: str
    source_version: str
    review_status: str = "pending_review"
    status: str = "draft"
    applies_sex: str | None = None
    applies_min_age: int | None = None
    applies_max_age: int | None = None
    conflict_group: str | None = None
    missing_info_prompt: str | None = None


@dataclass(frozen=True)
class CandidateBase:
    """候选的依据条目：可追溯到规则与发现。"""

    rule_code: str
    rule_version: str
    finding_id: str
    condition_code: str
    condition_name: str
    reason: str
    source: str
    source_version: str
    review_status: str


@dataclass
class Candidate:
    """检查候选：同一检查只出现一次，依据可多条。"""

    exam_code: str
    priority: int
    bases: list[CandidateBase] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        return [base.reason for base in self.bases]

    def as_dict(self) -> dict:
        return {
            "exam_code": self.exam_code,
            "priority": self.priority,
            "reasons": self.reasons,
            "bases": [
                {
                    "rule_code": b.rule_code,
                    "rule_version": b.rule_version,
                    "finding_id": b.finding_id,
                    "condition_code": b.condition_code,
                    "condition_name": b.condition_name,
                    "reason": b.reason,
                    "source": b.source,
                    "source_version": b.source_version,
                    "review_status": b.review_status,
                }
                for b in self.bases
            ],
        }


@dataclass(frozen=True)
class MissingInfoItem:
    """缺失信息提示：无法判定时明确列出。"""

    prompt: str
    related_code: str  # 规则编码或检查编码
    reason: str


@dataclass(frozen=True)
class ExcludedItem:
    """排除/冲突记录：可追踪的排除理由。"""

    exam_code: str
    rule_code: str
    reason: str
    kind: str  # applicability | conflict_group | draft


@dataclass
class CandidateResult:
    """H07 输出：候选 + 缺失信息 + 排除记录。"""

    version: str
    candidates: list[Candidate] = field(default_factory=list)
    missing_info: list[MissingInfoItem] = field(default_factory=list)
    excluded: list[ExcludedItem] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "candidates": [c.as_dict() for c in self.candidates],
            "missing_info": [
                {"prompt": m.prompt, "related_code": m.related_code, "reason": m.reason}
                for m in self.missing_info
            ],
            "excluded": [
                {
                    "exam_code": e.exam_code,
                    "rule_code": e.rule_code,
                    "reason": e.reason,
                    "kind": e.kind,
                }
                for e in self.excluded
            ],
        }
