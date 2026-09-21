"""字段映射模板加载与校验（H11）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
MAPPING_TEMPLATE_VERSION = "jiuhua-field-mapping-v1"

TARGET_ENTITIES = {
    "patient": ("anonymous_code", "sex", "birth_year"),
    "health_check": ("check_date", "institution", "source_batch"),
    "lab_metric": (
        "metric_name",
        "metric_code_hint",
        "original_value",
        "original_unit",
        "reference_text",
    ),
    "imaging_exam": ("exam_type", "body_part", "report_text", "exam_date"),
    "exam_item": ("item_name", "item_result_text"),
}

TARGET_VALUE_TYPES = {"numeric", "qualitative", "text", "date", "identifier"}
VERIFICATION_STATUSES = ("unverified", "verified")


@dataclass(frozen=True)
class MappingEntry:
    source_field: str
    source_description: str
    target_entity: str
    target_field: str
    value_type: str
    unit: str | None
    verification_status: str
    notes: str | None = None

    def as_dict(self) -> dict:
        return {
            "source_field": self.source_field,
            "source_description": self.source_description,
            "target_entity": self.target_entity,
            "target_field": self.target_field,
            "value_type": self.value_type,
            "unit": self.unit,
            "verification_status": self.verification_status,
            "notes": self.notes,
        }


class MappingValidationError(ValueError):
    """映射模板不合法。"""


def load_mapping_template(path: Path | None = None) -> list[MappingEntry]:
    target = path or DATA_DIR / "jiuhua_field_mapping_template.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    entries: list[MappingEntry] = []
    problems: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(payload["entries"]):
        where = f"{target.name}[{index}:{raw.get('source_field', '?')}]"
        source_field = str(raw.get("source_field", "")).strip()
        if not source_field:
            problems.append(f"{where}: 缺少 source_field")
            continue
        if source_field in seen:
            problems.append(f"{where}: source_field 重复")
            continue
        seen.add(source_field)
        entity = raw.get("target_entity", "")
        field = raw.get("target_field", "")
        if entity not in TARGET_ENTITIES or field not in TARGET_ENTITIES[entity]:
            problems.append(f"{where}: 未知目标 {entity}.{field}")
            continue
        if raw.get("value_type") not in TARGET_VALUE_TYPES:
            problems.append(f"{where}: 非法 value_type {raw.get('value_type')!r}")
        status = raw.get("verification_status", "unverified")
        if status not in VERIFICATION_STATUSES:
            problems.append(f"{where}: 非法 verification_status {status!r}")
        entries.append(
            MappingEntry(
                source_field=source_field,
                source_description=str(raw.get("source_description", "")),
                target_entity=entity,
                target_field=field,
                value_type=raw["value_type"],
                unit=raw.get("unit"),
                verification_status=status,
                notes=raw.get("notes"),
            )
        )
    if problems:
        raise MappingValidationError("\n".join(problems))
    return entries


class FieldMappingRegistry:
    """字段映射模板：登记/核对/未知字段入队。"""

    VERSION = MAPPING_TEMPLATE_VERSION

    def __init__(self, entries: list[MappingEntry]) -> None:
        self._entries = {entry.source_field: entry for entry in entries}

    @classmethod
    def load_builtin(cls) -> FieldMappingRegistry:
        return cls(load_mapping_template())

    def lookup(self, source_field: str) -> MappingEntry | None:
        return self._entries.get((source_field or "").strip())

    def entries(self) -> list[MappingEntry]:
        return [self._entries[k] for k in sorted(self._entries)]

    def unknown_source_fields(self, fields: list[str]) -> list[str]:
        """数据中出现但模板未登记的字段：保留待确认，不猜。"""
        return sorted(
            {f.strip() for f in fields if f.strip() and f.strip() not in self._entries}
        )

    def unverified_entries(self) -> list[MappingEntry]:
        return [e for e in self.entries() if e.verification_status == "unverified"]
