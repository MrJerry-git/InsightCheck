"""行 → 标准化条目的解析逻辑。

硬性规则（TEAM_TASKS_V2.md H03）：
- 原值永远保留（raw_* 字段）；
- 单位只有命中字典登记的换算依据才转换，否则保留原单位并显式标记；
- 数值/定性/文字三种值类型都支持；
- 未登记指标/定性值保留原貌进入待映射队列，不丢弃、不猜；
- 有量纲指标未提供单位（或空白单位）时，不自动赋予标准单位，标记
  ``unit_missing`` 且不生成可比较数值，等待人工确认（PR #19 审核 P1）。
"""

from __future__ import annotations

import re

from app.tabular_parsing.schemas import (
    ColumnMap,
    DictionaryEntryLike,
    DictionaryLike,
    ParsedMetricEntry,
    ParsedTabularReport,
    ParseIssue,
    UnmappedItem,
)

_NUMERIC_RE = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")
# 仅做符号/大小写归一，不做语义合并（如 IU/L 与 U/L 保持不同单位）。
_UNIT_ALIAS = {
    "10^9/l": "10*9/l",
    "10^12/l": "10*12/l",
    "μmol/l": "umol/l",
}


def normalize_unit(unit: str | None) -> str | None:
    """单位比较用归一：去空白、小写、^→*、μ→u。仅用于匹配，不改存储。"""
    if unit is None:
        return None
    cleaned = unit.strip().lower().replace(" ", "").replace("^", "*").replace("μ", "u")
    return _UNIT_ALIAS.get(cleaned, cleaned)


def parse_numeric(raw: str) -> float | None:
    """解析数值文本；千分位逗号可接受，其余非数值返回 None（不猜）。"""
    text = raw.strip()
    if not text or not _NUMERIC_RE.match(text):
        return None
    return float(text.replace(",", ""))


class TabularReportParser:
    """H03 表格解析服务。"""

    VERSION = "tabular-parsing-v1"

    def __init__(self, dictionary: DictionaryLike, columns: ColumnMap | None = None) -> None:
        self._dictionary = dictionary
        self._columns = columns or ColumnMap()

    def parse(self, source_name: str, rows: list[dict[str, str]]) -> ParsedTabularReport:
        issues: list[ParseIssue] = []
        entries: list[ParsedMetricEntry] = []
        unmapped: list[UnmappedItem] = []

        headers = list(rows[0].keys()) if rows else []
        mapping = self._columns.resolve(headers)
        if mapping["item"] is None or mapping["result"] is None:
            issues.append(
                ParseIssue(
                    source_name=source_name,
                    row_index=0,
                    column=",".join(headers),
                    field="header",
                    message="未识别到\"项目\"与\"结果\"列，请检查表头（支持自定义列名映射）",
                )
            )
            return ParsedTabularReport(
                source_name=source_name, entries=entries, issues=issues, unmapped=unmapped
            )

        for row_index, row in enumerate(rows, start=1):
            item_col = str(mapping["item"])
            raw_name = (row.get(item_col) or "").strip()
            if not raw_name:
                # 整行为空 → 跳过不算错误；有结果但没项目名 → 逐项错误
                result_col = str(mapping["result"])
                if (row.get(result_col) or "").strip():
                    issues.append(
                        ParseIssue(
                            source_name=source_name,
                            row_index=row_index,
                            column=item_col,
                            field="项目",
                            message="项目名称为空",
                        )
                    )
                continue

            entry, row_issues, row_unmapped = self._parse_row(
                source_name=source_name,
                row_index=row_index,
                row=row,
                mapping=mapping,
                raw_name=raw_name,
            )
            entries.append(entry)
            issues.extend(row_issues)
            unmapped.extend(row_unmapped)

        entries.sort(key=lambda e: (e.row_index, e.column_name))
        return ParsedTabularReport(
            source_name=source_name, entries=entries, issues=issues, unmapped=unmapped
        )

    # ---- 单行解析 ----

    def _parse_row(
        self,
        source_name: str,
        row_index: int,
        row: dict[str, str],
        mapping: dict[str, str | None],
        raw_name: str,
    ) -> tuple[ParsedMetricEntry, list[ParseIssue], list[UnmappedItem]]:
        issues: list[ParseIssue] = []
        unmapped: list[UnmappedItem] = []

        item_col = str(mapping["item"])
        result_col = str(mapping["result"])
        unit_col = mapping["unit"]
        ref_col = mapping["reference"]
        hint_col = mapping["hint"]
        page_col = mapping["page"]

        raw_value = (row.get(result_col) or "").strip()
        raw_unit = (row.get(unit_col) or "").strip() if unit_col else ""
        raw_reference = (row.get(ref_col) or "").strip() if ref_col else None
        report_hint = (row.get(hint_col) or "").strip() if hint_col else None
        page_hint = (row.get(page_col) or "").strip() if page_col else None

        entry = ParsedMetricEntry(
            raw_name=raw_name,
            raw_value=raw_value,
            raw_unit=raw_unit or None,
            raw_reference=raw_reference or None,
            report_hint=report_hint or None,
            page_hint=page_hint or None,
            row_index=row_index,
            column_name=item_col,
        )

        found = self._dictionary.lookup(raw_name)
        if found is None:
            entry.status = "unmapped"
            entry.value_type = "text"
            entry.text_value = raw_value or None
            issues.append(
                ParseIssue(
                    source_name=source_name,
                    row_index=row_index,
                    column=item_col,
                    field="项目",
                    message=f"未登记指标：{raw_name}（已进入待映射队列）",
                    severity="info",
                )
            )
            unmapped.append(
                UnmappedItem(
                    raw_name=raw_name,
                    raw_value=raw_value,
                    reason="name_not_registered",
                    row_index=row_index,
                    context=source_name,
                )
            )
            return entry, issues, unmapped

        entry.canonical_code = found.code
        entry.value_type = found.value_type
        if found.value_type == "numeric":
            self._apply_numeric(entry, found, source_name, row_index, result_col, issues)
        elif found.value_type == "qualitative":
            self._apply_qualitative(
                entry, found, source_name, row_index, result_col, raw_value, issues, unmapped
            )
        else:  # text / structured：原样保留
            entry.text_value = raw_value or None
            entry.status = "mapped" if raw_value else "invalid_value"
            if not raw_value:
                issues.append(
                    ParseIssue(
                        source_name=source_name,
                        row_index=row_index,
                        column=result_col,
                        field="结果",
                        message=f"{raw_name}：结果为空",
                    )
                )
        return entry, issues, unmapped

    def _apply_numeric(
        self,
        entry: ParsedMetricEntry,
        found: DictionaryEntryLike,
        source_name: str,
        row_index: int,
        result_col: str,
        issues: list[ParseIssue],
    ) -> None:
        value = parse_numeric(entry.raw_value)
        if value is None:
            entry.status = "invalid_value"
            entry.text_value = entry.raw_value or None
            issues.append(
                ParseIssue(
                    source_name=source_name,
                    row_index=row_index,
                    column=result_col,
                    field="结果",
                    message=f"{entry.raw_name}：数值无法解析（原值保留：{entry.raw_value!r}）",
                )
            )
            return

        standard = found.standard_unit or ""
        raw_unit_norm = normalize_unit(entry.raw_unit)
        standard_norm = normalize_unit(standard)
        entry.canonical_value = value

        # 字典未登记标准单位：视为无量纲指标，按原值映射，不需要单位确认。
        if not standard:
            entry.canonical_unit = entry.raw_unit
            entry.status = "mapped"
            return

        # 有量纲指标但未提供单位（缺失或空白）：不猜测、不赋标准单位。
        # 保留原值，标为待确认，且不生成可比较数值，避免下游当作已标准化数据
        # 参与异常判定与趋势比较（PR #19 审核 P1）。
        if raw_unit_norm is None:
            entry.canonical_value = None
            entry.canonical_unit = None
            entry.status = "unit_missing"
            entry.unit_confirmation_required = True
            issues.append(
                ParseIssue(
                    source_name=source_name,
                    row_index=row_index,
                    column=result_col,
                    field="单位",
                    message=(
                        f"{entry.raw_name}：未提供单位，标准单位为 {standard}，"
                        f"原值 {entry.raw_value!r} 已保留；需人工确认单位后才能比较"
                    ),
                    severity="warning",
                )
            )
            return

        if raw_unit_norm == standard_norm:
            entry.canonical_unit = standard
            entry.status = "mapped"
            return

        conversion = self._find_conversion(found, entry.raw_unit, standard)
        if conversion is None:
            entry.canonical_unit = entry.raw_unit
            entry.status = "unit_unconverted"
            issues.append(
                ParseIssue(
                    source_name=source_name,
                    row_index=row_index,
                    column=result_col,
                    field="单位",
                    message=(
                        f"{entry.raw_name}：单位 {entry.raw_unit} 与标准单位 {standard}"
                        " 无登记换算依据，保留原单位"
                    ),
                    severity="warning",
                )
            )
            return

        factor, offset, basis = conversion
        entry.canonical_value = round(value * factor + offset, 6)
        entry.canonical_unit = standard
        entry.conversion_basis = basis
        entry.status = "mapped"

    def _find_conversion(
        self, found: DictionaryEntryLike, from_unit: str | None, to_unit: str
    ) -> tuple[float, float, str] | None:
        """只接受字典登记过依据的正向换算，不做逆向推断。"""
        source = normalize_unit(from_unit)
        target = normalize_unit(to_unit)
        if source is None:
            return None
        for conv in found.unit_conversions:
            if normalize_unit(conv.from_unit) == source and normalize_unit(conv.to_unit) == target:
                return (conv.factor, conv.offset, conv.basis)
        return None

    def _apply_qualitative(
        self,
        entry: ParsedMetricEntry,
        found: DictionaryEntryLike,
        source_name: str,
        row_index: int,
        result_col: str,
        raw_value: str,
        issues: list[ParseIssue],
        unmapped: list[UnmappedItem],
    ) -> None:
        allowed = {v.strip() for v in found.qualitative_values}
        text = raw_value.strip()
        if text in allowed:
            entry.qualitative_status = text
            entry.text_value = text
            entry.status = "mapped"
            return
        entry.text_value = text or None
        entry.status = "unregistered_qualitative"
        message = f"{entry.raw_name}：定性值 {text!r} 不在登记允许值内，保留原文"
        unmapped.append(
            UnmappedItem(
                raw_name=entry.raw_name,
                raw_value=text,
                reason="qualitative_value_not_registered",
                row_index=row_index,
                context=source_name,
            )
        )
        issues.append(
            ParseIssue(
                source_name=source_name,
                row_index=row_index,
                column=result_col,
                field="结果",
                message=message,
                severity="warning",
            )
        )
