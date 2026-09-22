"""生成 H04 OCR 实际运行记录（PR #20 审核要求）。

用法：
    python backend/scripts/ocr_smoke.py

依赖（未安装时脚本会明确报错，不生成伪造记录）：
    pip install pymupdf rapidocr-onnxruntime

脚本构造三类真实样例 PDF（全扫描 2 页、文字+扫描混合、文字+扫描+空白三页），
用真实渲染器与 OCR 引擎执行逐页抽取，把版本、样例、结果写入
docs/ocr-run-record.json，供人工核对与回归比对。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.report_extraction import (  # noqa: E402
    PyMuPdfRenderer,
    RapidOcrAdapter,
    ReportTextExtractor,
)

GROUND_TRUTH = [
    "Total Cholesterol 5.2 mmol/L",
    "Fasting Glucose 6.1 mmol/L",
]


def _version(module_name: str) -> str:
    try:
        module = __import__(module_name)
    except ImportError:
        return "not-installed"
    for attr in ("__version__", "version"):
        value = getattr(module, attr, None)
        if isinstance(value, str):
            return value
    try:
        import importlib.metadata as metadata

        return metadata.version(module_name.replace("_", "-"))
    except Exception:
        return "unknown"


def build_scanned(path: str, pages_text: list[str]) -> None:
    """把文字页光栅化后重新嵌入，得到无文本层的"扫描件"。"""
    import fitz

    out = fitz.open()
    for text in pages_text:
        src = fitz.open()
        page = src.new_page()
        for index, line in enumerate(text.split("\n")):
            page.insert_text((72, 100 + 24 * index), line, fontsize=14)
        pixmap = page.get_pixmap(dpi=200)
        new_page = out.new_page()
        new_page.insert_image(fitz.Rect(0, 0, 612, 792), pixmap=pixmap)
        src.close()
    out.save(path)
    out.close()


def build_mixed(path: str, text_page: str, scanned_pages: list[str]) -> None:
    import fitz

    out = fitz.open()
    page = out.new_page()
    page.insert_text((72, 100), text_page, fontsize=14)
    for text in scanned_pages:
        src = fitz.open()
        src_page = src.new_page()
        for index, line in enumerate(text.split("\n")):
            src_page.insert_text((72, 100 + 24 * index), line, fontsize=14)
        pixmap = src_page.get_pixmap(dpi=200)
        target = out.new_page()
        target.insert_image(fitz.Rect(0, 0, 612, 792), pixmap=pixmap)
        src.close()
    out.save(path)
    out.close()


def run_case(extractor: ReportTextExtractor, name: str, path: str) -> dict:
    with open(path, "rb") as handle:
        content = handle.read()
    started = time.time()
    document = extractor.extract(name, content, ".pdf")
    elapsed = round(time.time() - started, 3)
    return {
        "sample": name,
        "status": document.status,
        "note": document.note,
        "page_count": document.page_count,
        "pages": [page.as_dict() for page in document.pages],
        "failed_pages": document.failed_pages,
        "ocr_pages": document.ocr_pages,
        "lines": [
            {"page_no": line.page_no, "line_no": line.line_no, "text": line.text}
            for line in document.lines
        ],
        "seconds": elapsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "ocr-run-record.json"
        ),
    )
    args = parser.parse_args()

    ocr = RapidOcrAdapter()
    renderer = PyMuPdfRenderer()
    if not ocr.is_available() or not renderer.is_available():
        print("OCR 环境不可用，未生成运行记录：", ocr.install_hint(), renderer.install_hint())
        return 1

    extractor = ReportTextExtractor(ocr_engine=ocr, pdf_renderer=renderer)
    scanned_text = "\n".join(GROUND_TRUTH)

    with tempfile.TemporaryDirectory() as tmp:
        scan_path = os.path.join(tmp, "scan_2p.pdf")
        mixed_path = os.path.join(tmp, "mixed.pdf")
        multi_path = os.path.join(tmp, "multi_3p.pdf")
        build_scanned(scan_path, [scanned_text, scanned_text])
        build_mixed(mixed_path, "Lab Report WBC 6.2 10*9/L 3.5-9.5", [scanned_text])
        build_mixed(multi_path, "Page one text layer", [scanned_text, ""])

        cases = [
            run_case(extractor, "scan_2p.pdf", scan_path),
            run_case(extractor, "mixed.pdf", mixed_path),
            run_case(extractor, "multi_3p.pdf", multi_path),
        ]

    record = {
        "generated_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "ocr_engine": ocr.engine_name,
            "pdf_renderer": renderer.renderer_name,
            "versions": {
                "pymupdf": _version("fitz"),
                "rapidocr_onnxruntime": _version("rapidocr_onnxruntime"),
                "pypdf": _version("pypdf"),
            },
        },
        "ground_truth": GROUND_TRUTH,
        "cases": cases,
    }

    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"运行记录已写入 {output}")
    for case in cases:
        print(
            f"  {case['sample']}: status={case['status']} "
            f"ocr_pages={case['ocr_pages']} failed_pages={case['failed_pages']} "
            f"{case['seconds']}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
