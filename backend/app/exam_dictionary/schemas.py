"""体检字典与关联目录的数据结构。

所有字段均可由 JSON 内容文件直接构造；校验规则集中在
``app.exam_dictionary.catalog`` 的加载器中，保证非法数据在加载时报错，
而不是在使用时产生不一致结果。
"""

from __future__ import annotations

from dataclasses import dataclass

VALUE_TYPES = ("numeric", "qualitative", "text", "structured")
ENTRY_KINDS = ("metric", "exam_item")
REVIEW_STATUSES = ("pending_review", "reviewed")
ENTRY_STATUSES = ("active", "pending_mapping")
RELATION_TYPES = (
    "abnormality_suggests",
    "finding_observation",
    "risk_factor",
)
DIRECTIONS = ("high", "low", "any", "qualitative_positive", "text_contains")


@dataclass(frozen=True)
class ReferenceRange:
    """参考区间：逐条登记出处与适用条件，无依据的区间不登记。"""

    population: str
    min_value: float | None
    max_value: float | None
    unit: str
    source: str
    source_version: str
    review_status: str = "pending_review"


@dataclass(frozen=True)
class UnitConversion:
    """仿射换算：to_value = raw_value * factor + offset，必须登记依据。"""

    from_unit: str
    to_unit: str
    factor: float
    offset: float = 0.0
    basis: str = ""


@dataclass(frozen=True)
class CatalogEntry:
    """字典条目：指标或检查项目。编码稳定，别名可扩展。"""

    code: str
    entry_kind: str
    display_name: str
    aliases: tuple[str, ...] = ()
    category: str = ""
    system: str = ""
    value_type: str = "numeric"
    standard_unit: str | None = None
    unit_conversions: tuple[UnitConversion, ...] = ()
    reference_ranges: tuple[ReferenceRange, ...] = ()
    expected_qualitative: str | None = None
    qualitative_values: tuple[str, ...] = ()
    reference_note: str | None = None
    notes: str | None = None
    source: str = ""
    source_version: str = ""
    review_status: str = "pending_review"
    status: str = "active"

    def as_dict(self) -> dict:
        """供管理 API（T08）与前端字典页（C11）序列化。"""
        return {
            "code": self.code,
            "entry_kind": self.entry_kind,
            "display_name": self.display_name,
            "aliases": list(self.aliases),
            "category": self.category,
            "system": self.system,
            "value_type": self.value_type,
            "standard_unit": self.standard_unit,
            "unit_conversions": [
                {
                    "from_unit": c.from_unit,
                    "to_unit": c.to_unit,
                    "factor": c.factor,
                    "offset": c.offset,
                    "basis": c.basis,
                }
                for c in self.unit_conversions
            ],
            "reference_ranges": [
                {
                    "population": r.population,
                    "min_value": r.min_value,
                    "max_value": r.max_value,
                    "unit": r.unit,
                    "source": r.source,
                    "source_version": r.source_version,
                    "review_status": r.review_status,
                }
                for r in self.reference_ranges
            ],
            "expected_qualitative": self.expected_qualitative,
            "qualitative_values": list(self.qualitative_values),
            "reference_note": self.reference_note,
            "notes": self.notes,
            "source": self.source,
            "source_version": self.source_version,
            "review_status": self.review_status,
            "status": self.status,
        }


@dataclass(frozen=True)
class UnmappedMetric:
    """未知指标：保留原始名称进入待映射队列，不丢弃、不自动解释。"""

    raw_name: str
    context: str = ""
    first_seen_batch: str | None = None
    status: str = "pending_mapping"


@dataclass(frozen=True)
class FindingAssociation:
    """检查/指标与可能关联的健康问题（非确诊）。"""

    association_id: str
    exam_code: str
    condition_code: str
    condition_name: str
    relation_type: str
    direction: str
    evidence_note: str = ""
    text_pattern: str | None = None
    flag_value: str | None = None
    source: str = ""
    source_version: str = ""
    review_status: str = "pending_review"

    def as_dict(self) -> dict:
        return {
            "association_id": self.association_id,
            "exam_code": self.exam_code,
            "condition_code": self.condition_code,
            "condition_name": self.condition_name,
            "relation_type": self.relation_type,
            "direction": self.direction,
            "evidence_note": self.evidence_note,
            "text_pattern": self.text_pattern,
            "flag_value": self.flag_value,
            "source": self.source,
            "source_version": self.source_version,
            "review_status": self.review_status,
        }


@dataclass(frozen=True)
class InstitutionPackage:
    """机构套餐：通过引用字典编码表达不同机构的体检项目集合（版本化）。"""

    package_id: str
    version: str
    institution: str
    exam_item_codes: tuple[str, ...] = ()
    notes: str | None = None
    source: str = ""
    source_version: str = ""

    def as_dict(self) -> dict:
        return {
            "package_id": self.package_id,
            "version": self.version,
            "institution": self.institution,
            "exam_item_codes": list(self.exam_item_codes),
            "notes": self.notes,
            "source": self.source,
            "source_version": self.source_version,
        }
