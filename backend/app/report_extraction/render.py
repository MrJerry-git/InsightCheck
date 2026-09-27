"""PDF 页面渲染适配器：把无文本层的页面渲染成图像供 OCR 使用。

逐页 OCR 需要先把 PDF 页面光栅化。渲染器与 OCR 引擎一样通过构造注入，
缺省由 default_renderer() 按可用性自动选择：**优先 pypdfium2**
（BSD-3-Clause / Apache-2.0，宽松许可，main 智能导入 app/services/smart_import.py
已在用同一依赖，不引入新的许可义务），未安装时回退 PyMuPDF（**AGPL-3.0**，
商业使用需评估）；两者都不可用时返回 UnavailableRenderer，**显式不可用，
不返回假图像冒充成功**。

所有适配器均延迟导入：未安装对应库时 is_available()=False 并给出安装说明，
不影响其余功能。安装入口见 backend/pyproject.toml 的 `[project.optional-dependencies]`
之 `ocr` extra（`pip install -e '.[ocr]'`）。
"""

from __future__ import annotations

from typing import Protocol


class PdfRenderer(Protocol):
    """页面渲染接口：H04 扫描/混合 PDF 逐页 OCR 的依赖点。"""

    renderer_name: str

    def is_available(self) -> bool: ...

    def render_page(self, pdf_bytes: bytes, page_no: int) -> bytes | None: ...


class UnavailableRenderer:
    """缺省渲染器：显式不可用。"""

    renderer_name = "none"

    def is_available(self) -> bool:
        return False

    def render_page(self, pdf_bytes: bytes, page_no: int) -> bytes | None:
        return None

    def install_hint(self) -> str:
        return (
            "PDF 页面渲染器不可用：请安装 pypdfium2"
            "（pip install pypdfium2，或 pip install -e '.[ocr]'）后重试"
        )


class Pypdfium2Renderer:
    """pypdfium2 渲染器（**推荐**）：pip install pypdfium2。

    BSD-3-Clause / Apache-2.0 双许可（宽松，可用于商用）；与 main 既有智能导入
    （app/services/smart_import.py）使用同一依赖，不新增许可义务，
    因此作为 default_renderer() 的首选。
    """

    renderer_name = "pypdfium2"

    def __init__(self, dpi: int = 200) -> None:
        self._dpi = dpi
        self._import_error: str | None = None

    def _import(self) -> object | None:
        try:
            import pypdfium2  # type: ignore[import-not-found]  # 延迟导入
        except ImportError as exc:
            self._import_error = str(exc)
            return None
        return pypdfium2

    def is_available(self) -> bool:
        return self._import() is not None

    def install_hint(self) -> str:
        if self._import_error is None:
            return ""
        return (
            "PDF 页面渲染器 pypdfium2 未安装，无法把扫描页渲染为图像供 OCR；"
            "请执行 pip install pypdfium2（或 pip install -e '.[ocr]'）后重试"
        )

    def render_page(self, pdf_bytes: bytes, page_no: int) -> bytes | None:
        pdfium = self._import()
        if pdfium is None:
            return None
        from io import BytesIO

        scale = self._dpi / 72.0  # PDF 点(1/72 英寸) → 目标 dpi
        with pdfium.PdfDocument(pdf_bytes) as pdf:  # type: ignore[attr-defined]
            if page_no < 1 or page_no > len(pdf):
                return None
            page = pdf[page_no - 1]
            try:
                bitmap = page.render(scale=scale)
                try:
                    out = BytesIO()
                    bitmap.to_pil().save(out, format="PNG")
                    return out.getvalue()
                finally:
                    bitmap.close()
            finally:
                page.close()


class PyMuPdfRenderer:
    """PyMuPDF 渲染器（**可选回退**）：pip install pymupdf。

    AGPL-3.0 许可（商业使用需评估）；仅在未安装 pypdfium2 时由
    default_renderer() 回退使用，不作为默认方案。
    """

    renderer_name = "pymupdf"

    def __init__(self, dpi: int = 200) -> None:
        self._dpi = dpi
        self._import_error: str | None = None

    def _import(self) -> object | None:
        try:
            import fitz  # type: ignore[import-not-found]  # 延迟导入
        except ImportError as exc:
            self._import_error = str(exc)
            return None
        return fitz

    def is_available(self) -> bool:
        return self._import() is not None

    def install_hint(self) -> str:
        if self._import_error is None:
            return ""
        return (
            "PDF 页面渲染器 PyMuPDF 未安装，无法把扫描页渲染为图像供 OCR；"
            "请执行 pip install pymupdf 后重试"
        )

    def render_page(self, pdf_bytes: bytes, page_no: int) -> bytes | None:
        fitz = self._import()
        if fitz is None:
            return None
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            if page_no < 1 or page_no > document.page_count:
                return None
            page = document.load_page(page_no - 1)
            pixmap = page.get_pixmap(dpi=self._dpi)
            return pixmap.tobytes("png")
        finally:
            document.close()


def default_renderer() -> PdfRenderer:
    """按可用性选择首选渲染器：pypdfium2（宽松许可）优先，PyMuPDF 回退。

    两者都不可用时返回 UnavailableRenderer —— 显式不可用，不伪造渲染结果。
    """
    preferred = Pypdfium2Renderer()
    if preferred.is_available():
        return preferred
    fallback = PyMuPdfRenderer()
    if fallback.is_available():
        return fallback
    return UnavailableRenderer()
