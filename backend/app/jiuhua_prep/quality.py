"""数据质量摘要工具（H11）。

对符合映射模板的样例行输出逐字段计数/缺失率/取值样例；
**标签与随访字段是否存在一律标 to_be_verified**——样例文件里有列
不代表真实数据里可用，必须等数据到达后核验。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.jiuhua_prep.mapping import FieldMappingRegistry

LABEL_FOLLOWUP_KEYWORDS = ("label", "随访", "标签", "outcome", "followup", "diagnosis")
SAMPLE_VALUE_CAP = 10


@dataclass
class FieldQuality:
    source_field: str
    registered: bool
    row_count: int
    missing_count: int
    missing_rate: float
    sample_values: list[str] = field(default_factory=list)
    label_followup_status: str = "not_applicable"  # not_applicable | to_be_verified

    def as_dict(self) -> dict:
        return {
            "source_field": self.source_field,
            "registered": self.registered,
            "row_count": self.row_count,
            "missing_count": self.missing_count,
            "missing_rate": round(self.missing_rate, 4),
            "sample_values": list(self.sample_values),
            "label_followup_status": self.label_followup_status,
        }


@dataclass
class QualitySummary:
    row_count: int
    fields: list[FieldQuality] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "row_count": self.row_count,
            "fields": [f.as_dict() for f in self.fields],
            "unknown_fields": list(self.unknown_fields),
            "notes": list(self.notes),
        }


def summarize_quality(rows: list[dict[str, str]], registry: FieldMappingRegistry) -> QualitySummary:
    """输出逐字段质量摘要；只做统计，不做任何医学解释。"""
    if not rows:
        return QualitySummary(row_count=0, notes=["样例为空，仅产出空摘要"])

    headers: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            normalized = key.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                headers.append(normalized)

    unknown = registry.unknown_source_fields(headers)
    fields: list[FieldQuality] = []
    for name in sorted(headers):
        entry = registry.lookup(name)
        values = [(row.get(name) or "").strip() for row in rows]
        missing = sum(1 for v in values if not v)
        samples: list[str] = []
        for value in values:
            if value and value not in samples:
                samples.append(value)
            if len(samples) >= SAMPLE_VALUE_CAP:
                break
        is_label = any(keyword in name.lower() for keyword in LABEL_FOLLOWUP_KEYWORDS)
        fields.append(
            FieldQuality(
                source_field=name,
                registered=entry is not None,
                row_count=len(rows),
                missing_count=missing,
                missing_rate=missing / len(rows),
                sample_values=samples,
                label_followup_status="to_be_verified" if is_label else "not_applicable",
            )
        )
    notes = [
        "标签与随访字段一律标 to_be_verified：样例文件存在该列不代表真实数据可用",
    ]
    if unknown:
        notes.append(f"存在 {len(unknown)} 个模板未登记字段，已进入待确认清单，不做猜测映射")
    return QualitySummary(row_count=len(rows), fields=fields, unknown_fields=unknown, notes=notes)
