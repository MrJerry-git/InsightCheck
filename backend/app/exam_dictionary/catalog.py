"""字典与关联目录的加载、校验与查询。

加载时一次性校验全部数据（编码/别名冲突、值类型约束、来源必填），
校验失败抛出 :class:`DictionaryValidationError` 并汇总列出全部问题。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from app.exam_dictionary.schemas import (
    DIRECTIONS,
    ENTRY_KINDS,
    RELATION_TYPES,
    REVIEW_STATUSES,
    VALUE_TYPES,
    CatalogEntry,
    FindingAssociation,
    InstitutionPackage,
    ReferenceRange,
    UnitConversion,
    UnmappedMetric,
)

DATA_DIR = Path(__file__).parent / "data"

_REQUIRED_ENTRY_FIELDS = ("code", "entry_kind", "display_name", "category", "system")


class DictionaryValidationError(ValueError):
    """内容文件未通过校验；message 汇总列出全部问题。"""


def _normalize_name(raw: str) -> str:
    """查询归一：全角转半角、压缩空白、casefold。

    只用于检索匹配，不改动任何存储内容。
    """
    cleaned = raw.strip().casefold()
    table = {
        "（": "(",
        "）": ")",
        "，": ",",
        "：": ":",
        "　": " ",
        "－": "-",
    }
    for wide, narrow in table.items():
        cleaned = cleaned.replace(wide, narrow)
    return " ".join(cleaned.split())


def _require_text(errors: list[str], where: str, value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where}: 字段 {field} 必须是非空文本")
        return ""
    return value


def _parse_reference_range(raw: dict, where: str, errors: list[str]) -> ReferenceRange | None:
    population = _require_text(errors, where, raw.get("population"), "population")
    source = _require_text(errors, where, raw.get("source"), "source")
    source_version = _require_text(errors, where, raw.get("source_version"), "source_version")
    unit = _require_text(errors, where, raw.get("unit"), "unit")
    min_value = raw.get("min_value")
    max_value = raw.get("max_value")
    if min_value is None and max_value is None:
        errors.append(f"{where}: min_value 与 max_value 不能同时缺省")
    if min_value is not None:
        if not isinstance(min_value, (int, float)) or isinstance(min_value, bool):
            errors.append(f"{where}: min_value 必须是有限数字或 null")
            min_value = None
        elif not math.isfinite(float(min_value)):
            errors.append(f"{where}: min_value 必须是有限数字")
            min_value = None
    if max_value is not None:
        if not isinstance(max_value, (int, float)) or isinstance(max_value, bool):
            errors.append(f"{where}: max_value 必须是有限数字或 null")
            max_value = None
        elif not math.isfinite(float(max_value)):
            errors.append(f"{where}: max_value 必须是有限数字")
            max_value = None
    if min_value is not None and max_value is not None and min_value > max_value:
        errors.append(f"{where}: min_value 不能大于 max_value")
    review_status = raw.get("review_status", "pending_review")
    if review_status not in REVIEW_STATUSES:
        errors.append(f"{where}: 非法 review_status {review_status!r}")
    if errors:
        return None
    return ReferenceRange(
        population=population,
        min_value=min_value,
        max_value=max_value,
        unit=unit,
        source=source,
        source_version=source_version,
        review_status=review_status,
    )


def _parse_conversion(raw: dict, where: str, errors: list[str]) -> UnitConversion | None:
    from_unit = _require_text(errors, where, raw.get("from_unit"), "from_unit")
    to_unit = _require_text(errors, where, raw.get("to_unit"), "to_unit")
    basis = _require_text(errors, where, raw.get("basis"), "basis")
    factor = raw.get("factor")
    offset = raw.get("offset", 0.0)
    if not isinstance(factor, (int, float)) or isinstance(factor, bool):
        errors.append(f"{where}: factor 必须是数字")
        factor = None
    if factor is not None and factor == 0:
        errors.append(f"{where}: factor 不能为 0")
    if not isinstance(offset, (int, float)) or isinstance(offset, bool):
        errors.append(f"{where}: offset 必须是数字")
    if errors:
        return None
    return UnitConversion(
        from_unit=from_unit,
        to_unit=to_unit,
        factor=float(factor),
        offset=float(offset),
        basis=basis,
    )


def parse_entry(raw: dict, origin: str) -> CatalogEntry:
    """把一条 JSON 记录解析为 CatalogEntry；不合法处汇总进错误列表。"""
    errors: list[str] = []
    where = f"{origin}[{raw.get('code', '<missing code>')}]" if isinstance(raw, dict) else origin
    if not isinstance(raw, dict):
        raise DictionaryValidationError(f"{origin}: 条目必须是对象")
    for field_name in _REQUIRED_ENTRY_FIELDS:
        _require_text(errors, where, raw.get(field_name), field_name)
    value_type = raw.get("value_type", "numeric")
    if value_type not in VALUE_TYPES:
        errors.append(f"{where}: 非法 value_type {value_type!r}")
    entry_kind = raw.get("entry_kind", "")
    if entry_kind not in ENTRY_KINDS:
        errors.append(f"{where}: 非法 entry_kind {entry_kind!r}")
    review_status = raw.get("review_status", "pending_review")
    if review_status not in REVIEW_STATUSES:
        errors.append(f"{where}: 非法 review_status {review_status!r}")
    status = raw.get("status", "active")
    if status not in ("active", "pending_mapping"):
        errors.append(f"{where}: 非法 status {status!r}")
    _require_text(errors, where, raw.get("source"), "source")
    _require_text(errors, where, raw.get("source_version"), "source_version")

    aliases = raw.get("aliases", [])
    aliases_valid = isinstance(aliases, list) and all(
        isinstance(a, str) and a.strip() for a in aliases
    )
    if not aliases_valid:
        errors.append(f"{where}: aliases 必须是非空字符串列表")
        aliases = []

    standard_unit = raw.get("standard_unit")
    numeric_missing_unit = value_type == "numeric" and (
        not isinstance(standard_unit, str) or not standard_unit.strip()
    )
    if numeric_missing_unit:
        errors.append(f"{where}: 数值条目必须有 standard_unit")

    conversions: list[UnitConversion] = []
    raw_conversions = raw.get("unit_conversions", [])
    if not isinstance(raw_conversions, list):
        errors.append(f"{where}: unit_conversions 必须是列表")
    else:
        for i, conv in enumerate(raw_conversions):
            parsed = _parse_conversion(conv, f"{where}.unit_conversions[{i}]", errors)
            if parsed is not None:
                conversions.append(parsed)

    ranges: list[ReferenceRange] = []
    raw_ranges = raw.get("reference_ranges", [])
    if not isinstance(raw_ranges, list):
        errors.append(f"{where}: reference_ranges 必须是列表")
    else:
        for i, rng in enumerate(raw_ranges):
            parsed = _parse_reference_range(rng, f"{where}.reference_ranges[{i}]", errors)
            if parsed is not None:
                ranges.append(parsed)

    qualitative_values = raw.get("qualitative_values", [])
    expected = raw.get("expected_qualitative")
    if value_type == "qualitative":
        if not isinstance(qualitative_values, list) or not qualitative_values:
            errors.append(f"{where}: 定性类条目必须登记 qualitative_values")
        if expected is not None and not isinstance(expected, str):
            errors.append(f"{where}: expected_qualitative 必须是字符串")
    if value_type in ("text", "structured") and ranges:
        errors.append(f"{where}: 文字/结构类条目不应登记数值参考区间")

    if errors:
        raise DictionaryValidationError("\n".join(errors))
    return CatalogEntry(
        code=raw["code"].strip(),
        entry_kind=entry_kind,
        display_name=raw["display_name"].strip(),
        aliases=tuple(a.strip() for a in aliases),
        category=raw["category"].strip(),
        system=raw["system"].strip(),
        value_type=value_type,
        standard_unit=standard_unit,
        unit_conversions=tuple(conversions),
        reference_ranges=tuple(ranges),
        expected_qualitative=expected,
        qualitative_values=tuple(str(v) for v in qualitative_values),
        reference_note=raw.get("reference_note"),
        notes=raw.get("notes"),
        source=raw["source"].strip(),
        source_version=raw["source_version"].strip(),
        review_status=review_status,
        status=status,
    )


def parse_association(raw: dict, origin: str) -> FindingAssociation:
    if not isinstance(raw, dict):
        raise DictionaryValidationError(f"{origin}: 条目必须是对象")
    errors: list[str] = []
    where = f"{origin}[{raw.get('association_id', '<missing id>')}]"
    for field_name in ("association_id", "exam_code", "condition_code", "condition_name"):
        _require_text(errors, where, raw.get(field_name), field_name)
    relation_type = raw.get("relation_type", "")
    if relation_type not in RELATION_TYPES:
        errors.append(f"{where}: 非法 relation_type {relation_type!r}（目录层不表达确诊）")
    direction = raw.get("direction", "")
    if direction not in DIRECTIONS:
        errors.append(f"{where}: 非法 direction {direction!r}")
    _require_text(errors, where, raw.get("evidence_note"), "evidence_note")
    _require_text(errors, where, raw.get("source"), "source")
    _require_text(errors, where, raw.get("source_version"), "source_version")
    review_status = raw.get("review_status", "pending_review")
    if review_status not in REVIEW_STATUSES:
        errors.append(f"{where}: 非法 review_status {review_status!r}")
    text_pattern = raw.get("text_pattern")
    if text_pattern is not None and (
        not isinstance(text_pattern, str) or direction != "text_contains"
    ):
        errors.append(f"{where}: text_pattern 仅允许 direction=text_contains")
    flag_value = raw.get("flag_value")
    if flag_value is not None and (
        not isinstance(flag_value, str) or direction != "qualitative_positive"
    ):
        errors.append(f"{where}: flag_value 仅允许 direction=qualitative_positive")
    if errors:
        raise DictionaryValidationError("\n".join(errors))
    return FindingAssociation(
        association_id=raw["association_id"].strip(),
        exam_code=raw["exam_code"].strip(),
        condition_code=raw["condition_code"].strip(),
        condition_name=raw["condition_name"].strip(),
        relation_type=relation_type,
        direction=direction,
        evidence_note=raw["evidence_note"].strip(),
        text_pattern=text_pattern,
        flag_value=flag_value,
        source=raw["source"].strip(),
        source_version=raw["source_version"].strip(),
        review_status=review_status,
    )


def parse_package(raw: dict, origin: str) -> InstitutionPackage:
    if not isinstance(raw, dict):
        raise DictionaryValidationError(f"{origin}: 条目必须是对象")
    errors: list[str] = []
    where = origin
    for field_name in ("package_id", "version", "institution"):
        _require_text(errors, where, raw.get(field_name), field_name)
    codes = raw.get("exam_item_codes", [])
    codes_valid = isinstance(codes, list) and codes and all(
        isinstance(c, str) and c.strip() for c in codes
    )
    if not codes_valid:
        errors.append(f"{where}: exam_item_codes 必须是非空字符串列表")
    _require_text(errors, where, raw.get("source"), "source")
    _require_text(errors, where, raw.get("source_version"), "source_version")
    if errors:
        raise DictionaryValidationError("\n".join(errors))
    return InstitutionPackage(
        package_id=raw["package_id"].strip(),
        version=raw["version"].strip(),
        institution=raw["institution"].strip(),
        exam_item_codes=tuple(c.strip() for c in codes),
        notes=raw.get("notes"),
        source=raw["source"].strip(),
        source_version=raw["source_version"].strip(),
    )


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        raise DictionaryValidationError(f"内容文件不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - 防御式分支
        raise DictionaryValidationError(f"内容文件不是合法 JSON：{path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise DictionaryValidationError(f"内容文件缺少 entries 列表：{path}")
    return payload["entries"]


def load_entries(path: Path) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    for i, raw in enumerate(_load_json(path)):
        entries.append(parse_entry(raw, f"{path.name}[{i}]"))
    return entries


def load_associations(path: Path) -> list[FindingAssociation]:
    associations: list[FindingAssociation] = []
    for i, raw in enumerate(_load_json(path)):
        associations.append(parse_association(raw, f"{path.name}[{i}]"))
    return associations


class ExamDictionary:
    """H01 字典服务：编码/别名查询、类别检索、未知指标待映射队列。"""

    VERSION = "exam-dictionary-v1"

    def __init__(self, entries: list[CatalogEntry]) -> None:
        problems: list[str] = []
        seen_codes: dict[str, str] = {}
        seen_names: dict[str, str] = {}
        for entry in entries:
            if entry.code in seen_codes:
                problems.append(f"编码重复：{entry.code}（与 {seen_codes[entry.code]} 冲突）")
                continue
            seen_codes[entry.code] = entry.display_name
            names = [entry.display_name, *entry.aliases]
            for name in names:
                key = _normalize_name(name)
                if not key:
                    problems.append(f"条目 {entry.code} 存在空名称")
                    continue
                if key in seen_names and seen_names[key] != entry.code:
                    problems.append(
                        f"名称冲突：{name!r} 同时属于 {seen_names[key]} 与 {entry.code}"
                    )
                    continue
                seen_names[key] = entry.code
        if problems:
            raise DictionaryValidationError("\n".join(problems))
        self._entries = {entry.code: entry for entry in entries}
        self._by_name = seen_names
        self._unmapped: dict[str, UnmappedMetric] = {}

    @classmethod
    def load_builtin(cls) -> ExamDictionary:
        return cls(load_entries(DATA_DIR / "exam_catalog.json"))

    @classmethod
    def load_with_extensions(cls, extra_paths: list[Path]) -> ExamDictionary:
        """扩展登记机制：在内置目录上合并扩展文件（编码不可重复）。"""
        entries = load_entries(DATA_DIR / "exam_catalog.json")
        for path in extra_paths:
            entries.extend(load_entries(path))
        return cls(entries)

    def _index_size(self) -> int:
        return len(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def lookup(self, raw_name: str) -> CatalogEntry | None:
        if not raw_name or not raw_name.strip():
            return None
        code = self._by_name.get(_normalize_name(raw_name))
        return self._entries.get(code) if code else None

    def lookup_by_code(self, code: str) -> CatalogEntry | None:
        return self._entries.get((code or "").strip())

    def entries_by_category(self, category: str) -> list[CatalogEntry]:
        return sorted(
            (e for e in self._entries.values() if e.category == category),
            key=lambda e: e.code,
        )

    def entries_by_kind(self, entry_kind: str) -> list[CatalogEntry]:
        return sorted(
            (e for e in self._entries.values() if e.entry_kind == entry_kind),
            key=lambda e: e.code,
        )

    def all_codes(self) -> list[str]:
        return sorted(self._entries)

    # ---- 待映射队列：未知项保留原貌，等人工补映射 ----

    def register_unknown(
        self, raw_name: str, context: str = "", batch: str | None = None
    ) -> UnmappedMetric:
        key = _normalize_name(raw_name)
        if not key:
            raise DictionaryValidationError("register_unknown 需要非空原始名称")
        if key not in self._unmapped:
            self._unmapped[key] = UnmappedMetric(
                raw_name=raw_name.strip(), context=context, first_seen_batch=batch
            )
        return self._unmapped[key]

    def unmapped_queue(self) -> tuple[UnmappedMetric, ...]:
        return tuple(
            sorted(self._unmapped.values(), key=lambda m: _normalize_name(m.raw_name))
        )

    def resolve_unmapped(self, raw_name: str, code: str) -> bool:
        """人工补映射完成：从队列移除。条目必须已存在于字典。"""
        key = _normalize_name(raw_name)
        if key not in self._unmapped:
            return False
        if self.lookup_by_code(code) is None:
            raise DictionaryValidationError(f"无法关联到已登记编码：{code}")
        del self._unmapped[key]
        return True

    # ---- 机构套餐 ----

    def load_package(self, path: Path) -> InstitutionPackage:
        raw = json.loads(path.read_text(encoding="utf-8"))
        package = parse_package(raw, path.name)
        unknown = [
            c for c in package.exam_item_codes if self.lookup_by_code(c) is None
        ]
        if unknown:
            raise DictionaryValidationError(
                f"套餐 {package.package_id} 引用了未登记编码：{', '.join(unknown)}"
            )
        return package


class FindingCatalog:
    """H02 关联目录：检查/指标 → 可能关联的健康问题（非确诊）。"""

    VERSION = "finding-catalog-v1"

    def __init__(self, associations: list[FindingAssociation]) -> None:
        problems: list[str] = []
        seen: dict[str, str] = {}
        for association in associations:
            if association.association_id in seen:
                problems.append(
                    f"association_id 重复：{association.association_id}"
                    f"（与 {seen[association.association_id]} 冲突）"
                )
                continue
            seen[association.association_id] = association.condition_code
        if problems:
            raise DictionaryValidationError("\n".join(problems))
        self._associations = tuple(associations)

    @classmethod
    def load_builtin(cls) -> FindingCatalog:
        return cls(load_associations(DATA_DIR / "finding_associations.json"))

    def associations_for_exam(self, exam_code: str) -> list[FindingAssociation]:
        return sorted(
            (a for a in self._associations if a.exam_code == (exam_code or "").strip()),
            key=lambda a: a.association_id,
        )

    def conditions_for_exam(
        self, exam_code: str, direction: str
    ) -> list[FindingAssociation]:
        return [a for a in self.associations_for_exam(exam_code) if a.direction == direction]

    def validate_against(self, dictionary: ExamDictionary) -> list[str]:
        """与字典核对：exam_code 必须已登记，text_pattern 只用于文字类条目。"""
        problems: list[str] = []
        for association in self._associations:
            entry = dictionary.lookup_by_code(association.exam_code)
            if entry is None:
                problems.append(
                    f"{association.association_id}: exam_code 未登记 {association.exam_code}"
                )
                continue
            text_entry = entry.value_type in ("text", "structured")
            if (
                association.direction == "text_contains"
                and not text_entry
            ):
                problems.append(
                    f"{association.association_id}: text_contains 只适用于文字类条目"
                    f"（{entry.code} 是 {entry.value_type}）"
                )
            if text_entry and association.direction != "text_contains":
                problems.append(
                    f"{association.association_id}: 文字类条目 {entry.code} 只允许 text_contains"
                )
            if entry.value_type == "qualitative" and association.direction not in (
                "qualitative_positive",
                "any",
            ):
                problems.append(
                    f"{association.association_id}: 定性条目 {entry.code}"
                    " 只允许 qualitative_positive/any"
                )
            if entry.value_type == "numeric" and association.direction not in (
                "high",
                "low",
                "any",
            ):
                problems.append(
                    f"{association.association_id}: 数值条目 {entry.code} 只允许 high/low/any"
                )
        return sorted(problems)

    def as_dicts(self) -> list[dict]:
        return [a.as_dict() for a in sorted(self._associations, key=lambda a: a.association_id)]


def load_builtin_catalog() -> ExamDictionary:
    return ExamDictionary.load_builtin()


def load_builtin_associations() -> FindingCatalog:
    return FindingCatalog.load_builtin()
