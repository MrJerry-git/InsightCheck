"""报告文本抽取与结构化（H04）。

纯计算模块：txt 直接解码、PDF 走文本层（pypdf）、图片走可插拔 OCR
适配器（未安装引擎时显式不可用，不伪造文本）；结构化识别支持版式在
data/supported_layouts.json 登记，未识别版式显式返回 unknown_layout。
每个候选字段都携带原文定位（页码/行号/原文），供校对界面（C03）使用。
契约说明见 docs/H_SERIES_SERVICE_CONTRACTS.md 第五节。
"""

from app.report_extraction.ocr import OcrEngine, RapidOcrAdapter, UnavailableOcr
from app.report_extraction.render import (
    PdfRenderer,
    PyMuPdfRenderer,
    UnavailableRenderer,
)
from app.report_extraction.schemas import (
    ExtractedDocument,
    ExtractedLine,
    PageExtraction,
    StructuredField,
    StructuredReport,
)
from app.report_extraction.structure import ReportStructurer
from app.report_extraction.text_source import ReportTextExtractor

__all__ = [
    "ExtractedDocument",
    "ExtractedLine",
    "OcrEngine",
    "PageExtraction",
    "PdfRenderer",
    "PyMuPdfRenderer",
    "RapidOcrAdapter",
    "ReportStructurer",
    "ReportTextExtractor",
    "StructuredField",
    "StructuredReport",
    "UnavailableOcr",
    "UnavailableRenderer",
]
