"""表格解析的数据结构与字典接口协议。

字典协议（DictionaryLike）与 PR #9 契约第四节一致：解析器只依赖
``lookup`` 返回条目的少数字段，不绑定具体实现，便于 H01 字典合并前
独立测试、合并后直接组合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

ENTRY_STATUSES = (
    "mapped",
    "unit_unconverted",
    "invalid_value",
    "unregistered_qualitative",
    "unmapped",
)


class ConversionLike(Protocol):
    from_unit: str
    to_unit: str
    factor: float
    offset: float
    basis: str


class DictionaryEntryLike(Protocol):
    """解析器需要的字典条目面：值类型、标准单位、换算表与定性允许值。"""

    code: str
    display_name: str
    value_type: str
    standard_unit: str | None
    unit_conversions: tuple[ConversionLike, ...]
    qualitative_values: tuple[str, ...]


class DictionaryLike(Protocol):
    def lookup(self, raw_name: str) -> DictionaryEntryLike | None: ...


@dataclass(frozen=True)
class ColumnMap:
    """表头识别：默认覆盖常见体检报告列名，可按机构覆盖。"""

    item_names: tuple[str, ...] = ("项目", "项目名称", "名称", "指标", "指标名称")
    result_names: tuple[str, ...] = ("结果", "测定值", "检测结果", "数值")
    unit_names: tuple[str, ...] = ("单位", ...)
    reference_names: tuple[str, ...] = ("参考区间", "参考范围", "正常范围", "参考值")
    hint_names: tuple[str, ...] = ("提示", "标记", "异常标记", "flag")
    page_names: tuple[str, ...] = ("页码", "原文页")

    def resolve(self, headers: list[str]) -> dict[str, str | None]:
        """把表头映射到语义列；未识别的语义列为 None。"""
        found: dict[str, str | None] = {}
        normalized = {h.strip(): h for h in headers if isinstance(h, str)}
        for semantic, candidates in (
            ("item", self.item_names),
            ("result", self.result_names),
            ("unit", self.unit_names),
            ("reference", self.reference_names),
            ("hint", self.hint_names),
            ("page", self.page_names),
        ):
            found[semantic] = next((normalized[c] for c in candidates if c in normalized), None)
        return found


@dataclass(frozen=True)
class ParseIssue:
    """逐行逐列错误/警告；source/row/column 定位，供校对界面展示。"""

    source_name: str
    row_index: int
    column: str
    field: str
    message: str
    severity: str = "error"  # error | warning | info

    def as_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "row_index": self.row_index,
            "column": self.column,
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class UnmappedItem:
    """未知指标（或未登记定性值）：保留原貌进入待映射队列。"""

    raw_name: str
    raw_value: str = ""
    reason: str = "name_not_registered"
    row_index: int = -1
    context: str = ""


@dataclass
class ParsedMetricEntry:
    """单条标准化结果：原值永远保留，标准化结果另存。"""

    raw_name: str
    raw_value: str
    raw_unit: str | None = None
    raw_reference: str | None = None
    report_hint: str | None = None
    page_hint: str | None = None
    row_index: int = -1
    column_name: str = ""
    canonical_code: str | None = None
    value_type: str = "text"
    canonical_value: float | None = None
    canonical_unit: str | None = None
    qualitative_status: str | None = None
    text_value: str | None = None
    conversion_basis: str | None = None
    status: str = "unmapped"

    def as_dict(self) -> dict:
        return {
            "raw_name": self.raw_name,
            "raw_value": self.raw_value,
            "raw_unit": self.raw_unit,
            "raw_reference": self.raw_reference,
            "report_hint": self.report_hint,
            "page_hint": self.page_hint,
            "row_index": self.row_index,
            "column_name": self.column_name,
            "canonical_code": self.canonical_code,
            "value_type": self.value_type,
            "canonical_value": self.canonical_value,
            "canonical_unit": self.canonical_unit,
            "qualitative_status": self.qualitative_status,
            "text_value": self.text_value,
            "conversion_basis": self.conversion_basis,
            "status": self.status,
        }


@dataclass
class ParsedTabularReport:
    """一次解析的完整输出：条目 + 逐项问题 + 待映射队列。"""

    source_name: str
    entries: list[ParsedMetricEntry] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    unmapped: list[UnmappedItem] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "entries": [e.as_dict() for e in self.entries],
            "issues": [i.as_dict() for i in self.issues],
            "unmapped": [
                {
                    "raw_name": u.raw_name,
                    "raw_value": u.raw_value,
                    "reason": u.reason,
                    "row_index": u.row_index,
                    "context": u.context,
                }
                for u in self.unmapped
            ],
        }
