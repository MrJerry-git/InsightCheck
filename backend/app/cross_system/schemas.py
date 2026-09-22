"""跨系统汇总的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

VALUE_TYPES = ("numeric", "qualitative", "text")
COMPARABILITY = ("comparable", "single_observation", "incomparable_unit")


@dataclass(frozen=True)
class Observation:
    """一次检查观测：数值/定性/文字三种形态之一。

    reference_* 来自当次报告或字典登记，必须携带来源；record_ref
    指向记录 ID，供追溯与问答引用。
    """

    metric_code: str
    display_name: str
    value_type: str
    observed_at: date
    record_ref: str
    category: str = "uncategorized"
    system: str = "general"
    raw_value: str = ""
    canonical_value: float | None = None
    unit: str | None = None
    qualitative_status: str | None = None
    text_value: str | None = None
    reference_min: float | None = None
    reference_max: float | None = None
    reference_unit: str | None = None
    reference_source: str | None = None
    reference_population: str | None = None
    expected_qualitative: str | None = None
    report_flag: str | None = None


@dataclass(frozen=True)
class TimelinePoint:
    """数值时间线点：异常判定引用当次参考区间。"""

    observed_at: date
    value: float
    unit: str | None
    reference_min: float | None
    reference_max: float | None
    reference_source: str | None
    reference_population: str | None
    direction: str  # high | low | normal | no_reference
    record_ref: str
    report_flag: str | None = None


@dataclass
class NumericMetricSummary:
    metric_code: str
    display_name: str
    category: str
    system: str
    comparability: str
    comparability_reason: str | None
    trend: str  # MetricTrend 取值（RISING/FALLING/STABLE/FLUCTUATING/UNKNOWN）
    trend_reason: str | None
    unit: str | None
    timeline: list[TimelinePoint] = field(default_factory=list)
    abnormality_count: int = 0

    def as_dict(self) -> dict:
        return {
            "metric_code": self.metric_code,
            "display_name": self.display_name,
            "category": self.category,
            "system": self.system,
            "comparability": self.comparability,
            "comparability_reason": self.comparability_reason,
            "trend": self.trend,
            "trend_reason": self.trend_reason,
            "unit": self.unit,
            "abnormality_count": self.abnormality_count,
            "timeline": [
                {
                    "observed_at": p.observed_at.isoformat(),
                    "value": p.value,
                    "unit": p.unit,
                    "reference_min": p.reference_min,
                    "reference_max": p.reference_max,
                    "reference_source": p.reference_source,
                    "reference_population": p.reference_population,
                    "direction": p.direction,
                    "record_ref": p.record_ref,
                    "report_flag": p.report_flag,
                }
                for p in self.timeline
            ],
        }


@dataclass(frozen=True)
class QualitativeTimelineEntry:
    observed_at: date
    status: str
    expected: str | None
    reference_source: str | None
    direction: str  # abnormal | normal | no_reference
    record_ref: str
    report_flag: str | None = None


@dataclass
class QualitativeMetricSummary:
    metric_code: str
    display_name: str
    category: str
    system: str
    timeline: list[QualitativeTimelineEntry] = field(default_factory=list)
    abnormality_count: int = 0

    def as_dict(self) -> dict:
        return {
            "metric_code": self.metric_code,
            "display_name": self.display_name,
            "category": self.category,
            "system": self.system,
            "abnormality_count": self.abnormality_count,
            "timeline": [
                {
                    "observed_at": e.observed_at.isoformat(),
                    "status": e.status,
                    "expected": e.expected,
                    "reference_source": e.reference_source,
                    "direction": e.direction,
                    "record_ref": e.record_ref,
                    "report_flag": e.report_flag,
                }
                for e in self.timeline
            ],
        }


@dataclass(frozen=True)
class TextTimelineEntry:
    observed_at: date
    text: str
    record_ref: str
    report_flag: str | None = None


@dataclass
class TextMetricSummary:
    metric_code: str
    display_name: str
    category: str
    system: str
    timeline: list[TextTimelineEntry] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "metric_code": self.metric_code,
            "display_name": self.display_name,
            "category": self.category,
            "system": self.system,
            "timeline": [
                {
                    "observed_at": e.observed_at.isoformat(),
                    "text": e.text,
                    "record_ref": e.record_ref,
                    "report_flag": e.report_flag,
                }
                for e in self.timeline
            ],
        }


@dataclass
class AbnormalityItem:
    """异常清单条目：逐条引用当次参考区间来源与适用条件。"""

    metric_code: str
    display_name: str
    observed_at: date
    direction: str  # high | low | qualitative_mismatch
    value_text: str
    unit: str | None
    reference_text: str
    reference_source: str | None
    reference_population: str | None
    record_ref: str

    def as_dict(self) -> dict:
        return {
            "metric_code": self.metric_code,
            "display_name": self.display_name,
            "observed_at": self.observed_at.isoformat(),
            "direction": self.direction,
            "value_text": self.value_text,
            "unit": self.unit,
            "reference_text": self.reference_text,
            "reference_source": self.reference_source,
            "reference_population": self.reference_population,
            "record_ref": self.record_ref,
        }


@dataclass
class SystemGroup:
    """按 类别+系统 分组的汇总。"""

    category: str
    system: str
    numeric: list[NumericMetricSummary] = field(default_factory=list)
    qualitative: list[QualitativeMetricSummary] = field(default_factory=list)
    text: list[TextMetricSummary] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "system": self.system,
            "numeric": [n.as_dict() for n in self.numeric],
            "qualitative": [q.as_dict() for q in self.qualitative],
            "text": [t.as_dict() for t in self.text],
        }


@dataclass
class CrossSystemSummary:
    """H05 输出：多系统汇总 + 异常清单 + 显式说明。"""

    version: str
    as_of: date
    groups: list[SystemGroup] = field(default_factory=list)
    abnormalities: list[AbnormalityItem] = field(default_factory=list)
    excluded_future_count: int = 0
    excluded_record_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "as_of": self.as_of.isoformat(),
            "groups": [g.as_dict() for g in self.groups],
            "abnormalities": [a.as_dict() for a in self.abnormalities],
            "excluded_future_count": self.excluded_future_count,
            "excluded_record_refs": list(self.excluded_record_refs),
            "notes": list(self.notes),
        }
