"""版式结构化：从原文行识别候选字段与所见/结论段落。

支持的版式在 data/supported_layouts.json 登记并版本化；识别逻辑按
登记的 pattern_id 实现。全部模式都不命中时显式返回 unknown_layout，
不冒充结构化成功。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.report_extraction.schemas import (
    ExtractedDocument,
    ExtractedLine,
    StructuredField,
    StructuredReport,
)

DATA_DIR = Path(__file__).parent / "data"

_FINDING_HEADERS = ("影像所见", "超声所见", "检查所见", "所见")
_CONCLUSION_HEADERS = ("影像结论", "超声提示", "诊断意见", "影像诊断", "结论")
_VALUE_RE = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")
_ROW_SPLIT_RE = re.compile(r"\s{2,}|\t")


@dataclass(frozen=True)
class LayoutSpec:
    layout_id: str
    description: str
    pattern_ids: tuple[str, ...]
    version: str


def load_layouts() -> tuple[LayoutSpec, ...]:
    payload = json.loads((DATA_DIR / "supported_layouts.json").read_text(encoding="utf-8"))
    return tuple(
        LayoutSpec(
            layout_id=item["layout_id"],
            description=item["description"],
            pattern_ids=tuple(item["pattern_ids"]),
            version=item["version"],
        )
        for item in payload["layouts"]
    )


def _try_kv_row(line: ExtractedLine) -> StructuredField | None:
    """键值行：`项目：结果` 或 `项目: 结果 单位`。"""
    match = re.match(r"^(?P<name>[^：:]{1,40})[：:]\s*(?P<rest>.+)$", line.text)
    if not match:
        return None
    name = match.group("name").strip()
    rest = match.group("rest").strip()
    if not name or not rest:
        return None
    tokens = _ROW_SPLIT_RE.split(rest)
    value = tokens[0].strip()
    unit = tokens[1].strip() if len(tokens) >= 2 else None
    reference = tokens[2].strip() if len(tokens) >= 3 else None
    hint = tokens[3].strip() if len(tokens) >= 4 else None
    return StructuredField(
        name=name,
        value=value,
        unit=unit,
        reference=reference,
        hint=hint,
        page_no=line.page_no,
        line_no=line.line_no,
        raw_text=line.text,
    )


def _try_table_row(line: ExtractedLine) -> StructuredField | None:
    """行式检验单：`项目  结果  单位  参考区间  提示`（≥2 空格分隔）。"""
    tokens = [t.strip() for t in _ROW_SPLIT_RE.split(line.text) if t.strip()]
    if len(tokens) < 2:
        return None
    name, value = tokens[0], tokens[1]
    if len(name) < 2 or len(name) > 30:
        return None
    if not _VALUE_RE.match(value) and not _looks_qualitative(value):
        return None
    return StructuredField(
        name=name,
        value=value,
        unit=tokens[2] if len(tokens) >= 3 else None,
        reference=tokens[3] if len(tokens) >= 4 else None,
        hint=tokens[4] if len(tokens) >= 5 else None,
        page_no=line.page_no,
        line_no=line.line_no,
        raw_text=line.text,
    )


def _looks_qualitative(value: str) -> bool:
    return value in {"阴性", "阳性", "弱阳性", "±", "+", "++", "+++", "++++"}


class ReportStructurer:
    """H04 版式结构化服务。"""

    VERSION = "report-structuring-v1"

    def __init__(self, layouts: tuple[LayoutSpec, ...] | None = None) -> None:
        self._layouts = layouts or load_layouts()

    def structure(self, document: ExtractedDocument) -> StructuredReport:
        if document.status != "ok" or not document.lines:
            return StructuredReport(
                source_name=document.source_name,
                status="unknown_layout",
                note=f"原文抽取状态为 {document.status}，无法结构化",
            )

        sections = self._split_sections(document.lines)
        fields, matched_patterns = self._extract_fields(sections["body"])
        layout_id = self._match_layout(sections, matched_patterns)

        if layout_id is None:
            return StructuredReport(
                source_name=document.source_name,
                status="unknown_layout",
                note=(
                    "未识别的报告版式：未命中任何登记版式。"
                    "原文已保留，请人工校对或在 supported_layouts.json 登记新版式"
                ),
                findings=sections["findings"],
                conclusions=sections["conclusions"],
            )

        status = "structured" if fields or sections["conclusions"] else "partial"
        return StructuredReport(
            source_name=document.source_name,
            status=status,
            layout_id=layout_id,
            fields=fields,
            findings=sections["findings"],
            conclusions=sections["conclusions"],
        )

    # ---- 段落切分 ----

    def _split_sections(
        self, lines: list[ExtractedLine]
    ) -> dict[str, list[ExtractedLine]]:
        findings: list[ExtractedLine] = []
        conclusions: list[ExtractedLine] = []
        body: list[ExtractedLine] = []
        current = "body"
        for line in lines:
            stripped = line.text.strip()
            header = self._section_header(stripped)
            if header == "finding":
                current = "findings"
                continue
            if header == "conclusion":
                current = "conclusions"
                continue
            if current == "findings":
                findings.append(line)
            elif current == "conclusions":
                conclusions.append(line)
            else:
                body.append(line)
        return {"body": body, "findings": findings, "conclusions": conclusions}

    def _section_header(self, text: str) -> str | None:
        cleaned = text.rstrip("：: ").strip()
        if not cleaned or len(cleaned) > 12:
            return None
        if cleaned in _FINDING_HEADERS:
            return "finding"
        if cleaned in _CONCLUSION_HEADERS:
            return "conclusion"
        return None

    # ---- 字段抽取 ----

    def _extract_fields(
        self, lines: list[ExtractedLine]
    ) -> tuple[list[StructuredField], set[str]]:
        fields: list[StructuredField] = []
        matched: set[str] = set()
        for line in lines:
            table_field = _try_table_row(line)
            if table_field is not None:
                fields.append(table_field)
                matched.add("table_row")
                continue
            kv_field = _try_kv_row(line)
            if kv_field is not None:
                fields.append(kv_field)
                matched.add("kv_row")
        return fields, matched

    def _match_layout(
        self, sections: dict[str, list[ExtractedLine]], matched_patterns: set[str]
    ) -> str | None:
        """按注册表顺序，返回第一个声明了任一命中 pattern 的版式。"""
        for layout in self._layouts:
            if matched_patterns.intersection(layout.pattern_ids):
                return layout.layout_id
            if "imaging_sections" in layout.pattern_ids and (
                sections["findings"] or sections["conclusions"]
            ):
                return layout.layout_id
        return None
