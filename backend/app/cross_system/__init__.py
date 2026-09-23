"""跨系统趋势及异常整理（H05）。

纯计算模块：把数值/定性/文字检查记录按类别与系统组织为趋势、
状态时间线、文字对照与异常清单。异常判定只引用当次登记的参考区间
及其来源与适用条件；无参考区间不判定；单位缺失或不一致均判为不可比较
且不推断趋势（PR #21 P1），缺单位登记为待确认项供对话式追问；
不产出决策日期之后的数据。
契约说明见 docs/H_SERIES_SERVICE_CONTRACTS.md 第六节。
"""

from app.cross_system.schemas import (
    AbnormalityItem,
    CrossSystemSummary,
    MissingUnitItem,
    NumericMetricSummary,
    Observation,
    QualitativeMetricSummary,
    QualitativeTimelineEntry,
    SystemGroup,
    TextMetricSummary,
    TextTimelineEntry,
)
from app.cross_system.summarizer import CrossSystemSummarizer

__all__ = [
    "AbnormalityItem",
    "CrossSystemSummary",
    "CrossSystemSummarizer",
    "MissingUnitItem",
    "NumericMetricSummary",
    "Observation",
    "QualitativeMetricSummary",
    "QualitativeTimelineEntry",
    "SystemGroup",
    "TextMetricSummary",
    "TextTimelineEntry",
]
