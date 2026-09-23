"""抽取与结构化的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field

DOCUMENT_STATUSES = (
    "ok",
    "partial",
    "needs_ocr",
    "ocr_unavailable",
    "unsupported_format",
    "empty",
)
STRUCTURE_STATUSES = ("structured", "partial", "unknown_layout")

PAGE_EXTRACTION_STATUSES = ("text_layer", "ocr", "failed")


@dataclass(frozen=True)
class PageExtraction:
    """逐页抽取结果：无法处理的页必须显式登记，不能整体报成功（PR #20 P1）。"""

    page_no: int
    status: str
    reason: str | None = None

    def as_dict(self) -> dict:
        return {"page_no": self.page_no, "status": self.status, "reason": self.reason}


@dataclass(frozen=True)
class ExtractedLine:
    """一行原文，带页码与行号定位（均从 1 开始）。"""

    page_no: int
    line_no: int
    text: str

    def as_dict(self) -> dict:
        return {"page_no": self.page_no, "line_no": self.line_no, "text": self.text}


@dataclass
class ExtractedDocument:
    """一份报告的原文抽取结果；needs_ocr/ocr_unavailable 时不冒充文本。"""

    source_name: str
    status: str
    lines: list[ExtractedLine] = field(default_factory=list)
    page_count: int = 0
    note: str | None = None
    pages: list[PageExtraction] = field(default_factory=list)

    @property
    def failed_pages(self) -> list[int]:
        return [page.page_no for page in self.pages if page.status == "failed"]

    @property
    def ocr_pages(self) -> list[int]:
        return [page.page_no for page in self.pages if page.status == "ocr"]

    def as_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "status": self.status,
            "page_count": self.page_count,
            "note": self.note,
            "lines": [line.as_dict() for line in self.lines],
            "pages": [page.as_dict() for page in self.pages],
        }


@dataclass
class StructuredField:
    """结构化候选字段：保留原文与定位，供人工校对确认。"""

    name: str
    value: str
    page_no: int
    line_no: int
    unit: str | None = None
    reference: str | None = None
    hint: str | None = None
    raw_text: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "reference": self.reference,
            "hint": self.hint,
            "page_no": self.page_no,
            "line_no": self.line_no,
            "raw_text": self.raw_text,
        }


@dataclass
class StructuredReport:
    """结构化输出：候选字段 + 所见/结论段落 + 命中的版式。"""

    source_name: str
    status: str
    layout_id: str | None = None
    fields: list[StructuredField] = field(default_factory=list)
    findings: list[ExtractedLine] = field(default_factory=list)
    conclusions: list[ExtractedLine] = field(default_factory=list)
    note: str | None = None

    def as_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "status": self.status,
            "layout_id": self.layout_id,
            "fields": [f.as_dict() for f in self.fields],
            "findings": [line.as_dict() for line in self.findings],
            "conclusions": [line.as_dict() for line in self.conclusions],
            "note": self.note,
        }
