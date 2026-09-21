"""原文抽取：txt 解码、PDF 文本层（pypdf）、图片 OCR 适配。

扫描版 PDF（无文本层）返回显式状态 needs_ocr；图片在引擎不可用时
返回 ocr_unavailable，都不返回空文本冒充成功。
"""

from __future__ import annotations

from app.report_extraction.ocr import OcrEngine, UnavailableOcr
from app.report_extraction.schemas import ExtractedDocument, ExtractedLine

SUPPORTED_SUFFIXES = (".txt", ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


def _decode_text(content: bytes) -> str:
    """体检报告常见 UTF-8/GBK 编码；带 BOM 的交给 utf-8-sig。"""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文本编码既不是 UTF-8 也不是 GB18030，无法解码")


def _pdf_pages(content: bytes) -> tuple[list[tuple[int, list[str]]], bool]:
    """返回 [(page_no, [行文本])]; 第二个值表示是否为扫描版（无任何文本层）。"""
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    pages: list[tuple[int, list[str]]] = []
    has_text = False
    for page_no, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            has_text = True
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        pages.append((page_no, lines))
    return pages, not has_text


class ReportTextExtractor:
    """H04 原文抽取服务。"""

    VERSION = "report-extraction-v1"

    def __init__(self, ocr_engine: OcrEngine | None = None) -> None:
        self._ocr = ocr_engine or UnavailableOcr()

    def extract(self, source_name: str, content: bytes, suffix: str) -> ExtractedDocument:
        clean_suffix = suffix.lower().lstrip(".")
        clean_suffix = f".{clean_suffix}" if not suffix.startswith(".") else suffix.lower()
        if clean_suffix not in SUPPORTED_SUFFIXES:
            return ExtractedDocument(
                source_name=source_name,
                status="unsupported_format",
                note=f"不支持的格式 {clean_suffix}，支持：{', '.join(SUPPORTED_SUFFIXES)}",
            )

        if clean_suffix == ".txt":
            return self._from_text(source_name, _decode_text(content), page_count=1)

        if clean_suffix == ".pdf":
            pages, scanned = _pdf_pages(content)
            if scanned:
                return ExtractedDocument(
                    source_name=source_name,
                    status="needs_ocr",
                    page_count=len(pages),
                    note="PDF 无文本层（扫描件），需要 OCR 引擎",
                )
            lines: list[ExtractedLine] = []
            for page_no, page_lines in pages:
                lines.extend(
                    ExtractedLine(page_no=page_no, line_no=line_no, text=text)
                    for line_no, text in enumerate(page_lines, start=1)
                )
            return ExtractedDocument(
                source_name=source_name,
                status="ok",
                lines=lines,
                page_count=len(pages),
            )

        # 图片：交给注入的 OCR 引擎
        if not self._ocr.is_available():
            note = getattr(self._ocr, "install_hint", lambda: "OCR 引擎不可用")()
            return ExtractedDocument(
                source_name=source_name,
                status="ocr_unavailable",
                note=note or "OCR 引擎不可用",
            )
        recognized = self._ocr.recognize([content])
        return self._from_text(source_name, recognized[0] if recognized else "", page_count=1)

    def _from_text(
        self, source_name: str, text: str, page_count: int
    ) -> ExtractedDocument:
        lines = [
            ExtractedLine(page_no=1, line_no=line_no, text=line.strip())
            for line_no, line in enumerate(text.splitlines(), start=1)
            if line.strip()
        ]
        if not lines:
            return ExtractedDocument(
                source_name=source_name, status="empty", note="文档无有效文本内容"
            )
        return ExtractedDocument(
            source_name=source_name, status="ok", lines=lines, page_count=page_count
        )
