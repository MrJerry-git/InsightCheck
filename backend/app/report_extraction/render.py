"""PDF 页面渲染适配器：把无文本层的页面渲染成图像供 OCR 使用。

逐页 OCR 需要先把 PDF 页面光栅化。渲染器与 OCR 引擎一样通过构造注入，
缺省 UnavailableRenderer 显式不可用，不返回假图像冒充成功。
PyMuPdfRenderer 采用延迟导入：未安装 PyMuPDF 时 is_available()=False
并给出安装说明，不影响其余功能。
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
        return "PDF 页面渲染器不可用：请安装 PyMuPDF（pip install pymupdf）后重试"


class PyMuPdfRenderer:
    """PyMuPDF 渲染器：pip install pymupdf。

    AGPL-3.0 许可（商业使用需评估）；也可替换为 pdf2image + poppler。
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
