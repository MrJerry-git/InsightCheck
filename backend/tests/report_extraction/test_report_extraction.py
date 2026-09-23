"""H04 原文抽取与版式结构化。

自制最小 PDF 夹具（build_pdf 手工构造合法 PDF 字节）用于验证文本层
抽取、页码/行号定位；OCR 走显式不可用路径（未安装引擎不伪造文本）。
"""

from __future__ import annotations

import pytest

from app.report_extraction import (
    ExtractedDocument,
    ExtractedLine,
    PageExtraction,
    PyMuPdfRenderer,
    RapidOcrAdapter,
    ReportStructurer,
    ReportTextExtractor,
    UnavailableOcr,
    UnavailableRenderer,
)

# ---- 自制 PDF 夹具 ----


def _content_stream(lines: list[str]) -> bytes:
    parts = ["BT", "/F1 12 Tf", "14 TL", "1 0 0 1 72 750 Tm"]
    for index, line in enumerate(lines):
        if index > 0:
            parts.append("T*")
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        parts.append(f"({escaped}) Tj")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")


def build_pdf(pages_lines: list[list[str]]) -> bytes:
    """构造最小合法 PDF：每页一个内容流，共享 Helvetica 字体。"""
    page_count = len(pages_lines)
    streams = [_content_stream(lines) for lines in pages_lines]
    font_obj_no = 3 + 2 * page_count
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            "<< /Type /Pages /Kids ["
            + " ".join(f"{3 + 2 * i} 0 R" for i in range(page_count))
            + f"] /Count {page_count} >>"
        ).encode(),
    ]
    for index, stream in enumerate(streams):
        page_no = 3 + 2 * index
        stream_no = page_no + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_obj_no} 0 R >> >> "
                f"/Contents {stream_no} 0 R >>"
            ).encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj_no, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{obj_no} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode()
    return bytes(out)


# ---- 原文抽取 ----


def test_txt_utf8_and_gbk_decoding() -> None:
    extractor = ReportTextExtractor()
    utf8 = "血常规\n白细胞计数  6.2  10*9/L  3.5-9.5".encode()
    gbk = "血常规\n白细胞计数  6.2  10*9/L  3.5-9.5".encode("gb18030")
    for content in (utf8, gbk):
        document = extractor.extract("report.txt", content, ".txt")
        assert document.status == "ok"
        assert document.lines[0].text == "血常规"
        assert document.lines[1].line_no == 2


def test_pdf_text_layer_extracted_with_page_and_line_numbers() -> None:
    # 基础字体（Helvetica）只支持 WinAnsi；中文 PDF 依赖机构嵌入 CID 字体，
    # 属已知限制（见 docs/REUSABLE_COMPONENTS.md），此处用 ASCII 自制报告验证页码/行号。
    extractor = ReportTextExtractor()
    pdf = build_pdf(
        [
            ["Lab Report", "", "WBC  6.2  10*9/L  3.5-9.5"],
            ["ECG conclusion  sinus rhythm"],
        ]
    )
    document = extractor.extract("report.pdf", pdf, ".pdf")
    assert document.status == "ok"
    assert document.page_count == 2
    page1 = [line for line in document.lines if line.page_no == 1]
    page2 = [line for line in document.lines if line.page_no == 2]
    assert page1[0].line_no == 1 and page1[0].text == "Lab Report"
    assert any("WBC" in line.text for line in page1)
    assert any("ECG" in line.text for line in page2)


def test_scanned_pdf_without_text_layer_needs_ocr() -> None:
    # 自制"扫描件"：PDF 结构存在但内容流无文本
    extractor = ReportTextExtractor()
    pdf = build_pdf([[""], [""]])
    # build_pdf 过滤空行后内容流可能为空指令流，但文本为空
    document = extractor.extract("scan.pdf", pdf, ".pdf")
    assert document.status in ("needs_ocr", "empty")
    assert document.lines == []


def test_image_without_ocr_engine_is_explicitly_unavailable() -> None:
    extractor = ReportTextExtractor(ocr_engine=UnavailableOcr())
    document = extractor.extract("photo.jpg", b"\x89PNG-fake", ".png")
    assert document.status == "ocr_unavailable"
    assert document.lines == []
    assert document.note and "OCR" in document.note


def test_unsupported_format_is_rejected() -> None:
    extractor = ReportTextExtractor()
    document = extractor.extract("report.docx", b"whatever", ".docx")
    assert document.status == "unsupported_format"
    assert document.note and ".docx" in document.note


# ---- 逐页 OCR 测试替身 ----


class FakeRenderer:
    """把页面渲染成可辨识的字节，供 FakeOcr 断言"逐页调用"。"""

    renderer_name = "fake-renderer"

    def __init__(self, available: bool = True) -> None:
        self._available = available
        self.rendered: list[int] = []

    def is_available(self) -> bool:
        return self._available

    def render_page(self, pdf_bytes: bytes, page_no: int) -> bytes | None:
        if not self._available:
            return None
        self.rendered.append(page_no)
        return f"page-{page_no}".encode()


class FakeOcr:
    engine_name = "fake-ocr"

    def __init__(self, available: bool = True, raise_error: bool = False) -> None:
        self._available = available
        self._raise_error = raise_error
        self.recognized: list[bytes] = []

    def is_available(self) -> bool:
        return self._available

    def recognize(self, images: list[bytes]) -> list[str]:
        if self._raise_error:
            raise RuntimeError("OCR 引擎运行失败")
        self.recognized.extend(images)
        return [f"OCR[{image.decode()}] total_cholesterol 5.2 mmol/L" for image in images]


def test_empty_text_is_explicit() -> None:
    extractor = ReportTextExtractor()
    document = extractor.extract("blank.txt", b"\n\n  \n", ".txt")
    assert document.status == "empty"


def test_rapidocr_adapter_reports_unavailability_without_package() -> None:
    adapter = RapidOcrAdapter()
    if adapter.is_available():
        pytest.skip("rapidocr-onnxruntime 已安装，跳过不可用路径")
    assert adapter.is_available() is False
    assert "rapidocr-onnxruntime" in adapter.install_hint()
    with pytest.raises(RuntimeError):
        adapter.recognize([b"fake"])


# ---- PR #20 审核 P1：全扫描 / 混合 PDF 必须逐页处理 ----


def test_fully_scanned_pdf_calls_ocr_when_engine_injected() -> None:
    """审核复现：全扫描 PDF 以前直接返回 needs_ocr，即使 OCR 可用也不调用。"""
    ocr, renderer = FakeOcr(), FakeRenderer()
    extractor = ReportTextExtractor(ocr_engine=ocr, pdf_renderer=renderer)
    document = extractor.extract("scan.pdf", build_pdf([[""], [""]]), ".pdf")
    assert document.status == "ok", document.note
    assert renderer.rendered == [1, 2], "必须逐页渲染，不能只判断一次"
    assert len(ocr.recognized) == 2, "必须逐页调用 OCR"
    assert document.ocr_pages == [1, 2]
    assert document.failed_pages == []
    assert {line.page_no for line in document.lines} == {1, 2}


def test_fully_scanned_pdf_without_engine_reports_every_page() -> None:
    extractor = ReportTextExtractor()
    document = extractor.extract("scan.pdf", build_pdf([[""], [""]]), ".pdf")
    assert document.status == "needs_ocr"
    assert document.lines == []
    assert document.failed_pages == [1, 2]
    assert document.pages[0].reason == "ocr_unavailable"
    assert document.note and "ocr_unavailable" in document.note


def test_mixed_pdf_is_not_silently_ok_without_ocr() -> None:
    """审核复现：混合 PDF 只要一页有文字就返回 ok，无文本页被静默跳过。"""
    extractor = ReportTextExtractor()
    pdf = build_pdf([["Lab Report", "WBC  6.2  10*9/L"], [""]])
    document = extractor.extract("mixed.pdf", pdf, ".pdf")
    assert document.status == "partial", "存在未处理页时不能返回 ok"
    assert document.failed_pages == [2]
    assert {line.page_no for line in document.lines} == {1}
    assert document.note and "第 2 页" in document.note


def test_mixed_pdf_recovers_scanned_page_with_ocr() -> None:
    ocr, renderer = FakeOcr(), FakeRenderer()
    extractor = ReportTextExtractor(ocr_engine=ocr, pdf_renderer=renderer)
    pdf = build_pdf([["Lab Report", "WBC  6.2  10*9/L"], [""]])
    document = extractor.extract("mixed.pdf", pdf, ".pdf")
    assert document.status == "ok"
    assert renderer.rendered == [2], "只渲染无文本层的页"
    page2 = [line for line in document.lines if line.page_no == 2]
    assert page2 and "total_cholesterol" in page2[0].text
    assert document.ocr_pages == [2]


def test_multi_page_mixed_reports_each_failed_page() -> None:
    ocr, renderer = FakeOcr(), FakeRenderer(available=False)
    extractor = ReportTextExtractor(ocr_engine=ocr, pdf_renderer=renderer)
    pdf = build_pdf([["Page one text"], [""], ["Page three text"], [""]])
    document = extractor.extract("multi.pdf", pdf, ".pdf")
    assert document.status == "partial"
    assert document.failed_pages == [2, 4]
    assert document.pages[1].reason == "pdf_renderer_unavailable"
    assert {line.page_no for line in document.lines} == {1, 3}


def test_ocr_engine_error_is_explicit_not_swallowed() -> None:
    ocr, renderer = FakeOcr(raise_error=True), FakeRenderer()
    extractor = ReportTextExtractor(ocr_engine=ocr, pdf_renderer=renderer)
    pdf = build_pdf([["Lab Report"], [""]])
    document = extractor.extract("mixed.pdf", pdf, ".pdf")
    assert document.status == "partial"
    assert document.failed_pages == [2]
    assert (document.pages[1].reason or "").startswith("ocr_error")


def test_text_layer_pages_are_recorded_and_not_failed() -> None:
    extractor = ReportTextExtractor()
    pdf = build_pdf([["Lab Report"], ["ECG  sinus rhythm"]])
    document = extractor.extract("report.pdf", pdf, ".pdf")
    assert document.status == "ok"
    assert [page.status for page in document.pages] == ["text_layer", "text_layer"]
    assert document.failed_pages == []


def test_page_results_exposed_in_as_dict() -> None:
    extractor = ReportTextExtractor()
    pdf = build_pdf([["Lab Report"], [""]])
    payload = extractor.extract("mixed.pdf", pdf, ".pdf").as_dict()
    assert payload["status"] == "partial"
    assert payload["pages"][1] == {"page_no": 2, "status": "failed", "reason": "ocr_unavailable"}


def test_real_engine_scanned_and_mixed_pdf() -> None:
    """真实文件测试：引擎可用时，全扫描与混合 PDF 必须逐页 OCR 成功。"""
    import fitz

    ocr, renderer = RapidOcrAdapter(), PyMuPdfRenderer()
    if not ocr.is_available() or not renderer.is_available():
        pytest.skip("未安装 pymupdf / rapidocr-onnxruntime，跳过真实引擎测试")
    extractor = ReportTextExtractor(ocr_engine=ocr, pdf_renderer=renderer)

    scan_bytes = _rasterize_pdf(["Total Cholesterol 5.2 mmol/L"], fitz)
    document = extractor.extract("scan.pdf", scan_bytes, ".pdf")
    assert document.status == "ok", document.note
    assert document.pages[0].status == "ocr"
    assert any("5.2" in line.text for line in document.lines)

    mixed = fitz.open()
    page = mixed.new_page()
    page.insert_text((72, 100), "Lab Report WBC 6.2", fontsize=14)
    raster = _rasterize_pdf(["Fasting Glucose 6.1 mmol/L"], fitz)
    mixed.insert_pdf(fitz.open(stream=raster, filetype="pdf"))
    mixed_bytes = mixed.tobytes()
    mixed.close()

    document = extractor.extract("mixed.pdf", mixed_bytes, ".pdf")
    assert document.status == "ok", document.note
    assert [page.status for page in document.pages] == ["text_layer", "ocr"]
    assert any("WBC" in line.text for line in document.lines)
    assert any("6.1" in line.text for line in document.lines)


def _rasterize_pdf(lines: list[str], fitz) -> bytes:
    """把文字页光栅化后重新嵌入，得到无文本层的"扫描件"。"""
    source = fitz.open()
    page = source.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 100 + 24 * index), line, fontsize=14)
    pixmap = page.get_pixmap(dpi=200)
    out = fitz.open()
    target = out.new_page()
    target.insert_image(fitz.Rect(0, 0, 612, 792), pixmap=pixmap)
    data = out.tobytes()
    out.close()
    source.close()
    return data


def test_renderer_and_ocr_adapters_report_unavailability() -> None:
    renderer = UnavailableRenderer()
    assert renderer.is_available() is False
    assert renderer.render_page(b"", 1) is None
    assert renderer.install_hint()
    adapter = PyMuPdfRenderer()
    if adapter.is_available():
        pytest.skip("PyMuPDF 已安装，跳过不可用路径")
    assert adapter.is_available() is False
    assert "pymupdf" in adapter.install_hint().lower()


# ---- 版式结构化 ----


def document_from(lines: list[str]) -> ExtractedDocument:
    return ExtractedDocument(
        source_name="demo.txt",
        status="ok",
        lines=[
            ExtractedLine(page_no=1, line_no=i, text=text)
            for i, text in enumerate(lines, start=1)
            if text.strip()
        ],
        page_count=1,
    )


def test_lab_table_row_layout_structured() -> None:
    document = document_from(
        [
            "检验报告单",
            "白细胞计数  6.2  10*9/L  3.5-9.5",
            "血红蛋白  135  g/L  131-172  ↑",
        ]
    )
    report = ReportStructurer().structure(document)
    assert report.status == "structured"
    assert report.layout_id == "lab_table_row"
    assert len(report.fields) == 2
    first = report.fields[0]
    assert (first.name, first.value, first.unit, first.reference) == (
        "白细胞计数",
        "6.2",
        "10*9/L",
        "3.5-9.5",
    )
    assert first.hint is None
    assert first.page_no == 1 and first.line_no == 2
    assert first.raw_text == "白细胞计数  6.2  10*9/L  3.5-9.5"
    second = report.fields[1]
    assert second.name == "血红蛋白" and second.hint == "↑"
    assert second.value == "135" and second.reference == "131-172"


def test_kv_layout_structured() -> None:
    document = document_from(
        [
            "胸部正位摄影：双肺纹理清晰",
            "心影大小：正常",
        ]
    )
    report = ReportStructurer().structure(document)
    assert report.layout_id == "kv_report"
    assert report.fields[0].name == "胸部正位摄影"
    assert report.fields[0].value == "双肺纹理清晰"


def test_imaging_sections_split_findings_and_conclusions() -> None:
    document = document_from(
        [
            "超声所见",
            "肝形态大小正常，实质回声均匀。",
            "胆囊壁光滑，腔内未见异常回声。",
            "影像结论",
            "肝胆超声未见明显异常。",
            "建议年度复查。",
        ]
    )
    report = ReportStructurer().structure(document)
    assert report.layout_id == "imaging_section_report"
    assert [line.text for line in report.findings] == [
        "肝形态大小正常，实质回声均匀。",
        "胆囊壁光滑，腔内未见异常回声。",
    ]
    assert [line.text for line in report.conclusions] == [
        "肝胆超声未见明显异常。",
        "建议年度复查。",
    ]


def test_unknown_layout_is_explicit_not_fabricated() -> None:
    document = document_from(
        [
            "本报告仅说明受检者当日到检情况。",
            "如需了解详情请咨询体检中心前台。",
        ]
    )
    report = ReportStructurer().structure(document)
    assert report.status == "unknown_layout"
    assert report.layout_id is None
    assert report.note and "人工校对" in report.note


def test_structurer_passthrough_on_failed_extraction() -> None:
    document = ExtractedDocument(
        source_name="scan.pdf", status="needs_ocr", page_count=2
    )
    report = ReportStructurer().structure(document)
    assert report.status == "unknown_layout"
    assert report.note and "needs_ocr" in report.note


def test_prose_lines_do_not_become_fields() -> None:
    document = document_from(["窦性心律，未见明显异常。"])
    report = ReportStructurer().structure(document)
    assert report.fields == []
