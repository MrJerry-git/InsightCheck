"""原文抽取：txt 解码、PDF 文本层（pypdf）、图片 OCR 适配。

逐页处理 PDF：有文本层的页直接抽取；无文本层的页在渲染器与 OCR 引擎可用时
逐页渲染并 OCR（PR #20 P1）。任一只页无法处理都会在 pages/failed_pages 中
显式登记，整体状态为 partial / needs_ocr / empty，绝不整体报 ok。
图片在引擎不可用时返回 ocr_unavailable，都不返回空文本冒充成功。
"""

from __future__ import annotations

from app.report_extraction.ocr import OcrEngine, UnavailableOcr
from app.report_extraction.render import PdfRenderer, UnavailableRenderer
from app.report_extraction.schemas import (
    ExtractedDocument,
    ExtractedLine,
    PageExtraction,
)

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


def _pdf_pages(content: bytes) -> list[tuple[int, list[str]]]:
    """返回 [(page_no, [行文本])]；无文本层的页返回空列表，由调用方逐页处理。"""
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    pages: list[tuple[int, list[str]]] = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        pages.append((page_no, lines))
    return pages


class ReportTextExtractor:
    """H04 原文抽取服务。"""

    VERSION = "report-extraction-v1"

    def __init__(
        self,
        ocr_engine: OcrEngine | None = None,
        pdf_renderer: PdfRenderer | None = None,
    ) -> None:
        self._ocr = ocr_engine or UnavailableOcr()
        self._renderer = pdf_renderer or UnavailableRenderer()

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
            return self._extract_pdf(source_name, content)

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

    def _extract_pdf(self, source_name: str, content: bytes) -> ExtractedDocument:
        """逐页处理：有文本层直接抽取，无文本层逐页渲染 OCR。

        无法处理的页必须显式登记在 pages/failed_pages 中；只要有一页失败，
        整体状态只能是 partial（部分成功）或 needs_ocr/empty，绝不返回 ok。
        """
        pages = _pdf_pages(content)
        if not pages:
            return ExtractedDocument(
                source_name=source_name, status="empty", note="PDF 未解析到任何页面"
            )

        lines: list[ExtractedLine] = []
        page_results: list[PageExtraction] = []

        for page_no, page_lines in pages:
            if page_lines:
                lines.extend(
                    ExtractedLine(page_no=page_no, line_no=line_no, text=text)
                    for line_no, text in enumerate(page_lines, start=1)
                )
                page_results.append(PageExtraction(page_no=page_no, status="text_layer"))
                continue
            lines_from_ocr, page_result = self._ocr_page(content, page_no)
            if lines_from_ocr:
                lines.extend(
                    ExtractedLine(page_no=page_no, line_no=line_no, text=text)
                    for line_no, text in enumerate(lines_from_ocr, start=1)
                )
            page_results.append(page_result)

        failed = [page.page_no for page in page_results if page.status == "failed"]
        reasons = sorted({page.reason or "" for page in page_results if page.status == "failed"})

        if not lines:
            status = "needs_ocr" if failed else "empty"
            note = (
                f"全部 {len(pages)} 页均无文本层且未完成 OCR（{', '.join(reasons)}），"
                "未生成任何文本"
                if failed
                else "PDF 未提取到任何文本"
            )
        elif failed:
            status = "partial"
            note = (
                f"第 {', '.join(str(no) for no in failed)} 页未能抽取，"
                f"其余页结果可用；原因：{', '.join(reasons)}"
            )
        else:
            status = "ok"
            note = None

        return ExtractedDocument(
            source_name=source_name,
            status=status,
            lines=lines,
            page_count=len(pages),
            note=note,
            pages=page_results,
        )

    def _ocr_page(
        self, pdf_bytes: bytes, page_no: int
    ) -> tuple[list[str], PageExtraction]:
        """单页 OCR：返回（识别行, 逐页结果）；失败时行列表为空且原因明确。"""
        if not self._ocr.is_available():
            return [], PageExtraction(page_no, "failed", "ocr_unavailable")
        if not self._renderer.is_available():
            return [], PageExtraction(page_no, "failed", "pdf_renderer_unavailable")
        image = self._renderer.render_page(pdf_bytes, page_no)
        if not image:
            return [], PageExtraction(page_no, "failed", "pdf_page_render_failed")
        try:
            recognized = self._ocr.recognize([image])
        except Exception as exc:  # 引擎报错必须显式暴露，不能吞掉
            return [], PageExtraction(page_no, "failed", f"ocr_error: {exc}")
        text = recognized[0] if recognized else ""
        ocr_lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not ocr_lines:
            return [], PageExtraction(page_no, "failed", "ocr_empty_result")
        return ocr_lines, PageExtraction(page_no, "ocr")

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
