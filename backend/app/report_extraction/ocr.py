"""可插拔 OCR 引擎适配器。

引擎通过构造注入（王天一后续接入 settings）；缺省 UnavailableOcr
显式不可用。RapidOcrAdapter 采用延迟导入：未安装 rapidocr-onnxruntime
时 is_available()=False 并给出安装说明，不影响其余功能。
"""

from __future__ import annotations

from typing import Protocol


class OcrEngine(Protocol):
    """OCR 引擎接口：H10 组件清单中登记的接入点之一。"""

    engine_name: str

    def is_available(self) -> bool: ...

    def recognize(self, images: list[bytes]) -> list[str]: ...


class UnavailableOcr:
    """缺省引擎：显式不可用，绝不返回编造文本。"""

    engine_name = "none"

    def is_available(self) -> bool:
        return False

    def recognize(self, images: list[bytes]) -> list[str]:
        raise RuntimeError("OCR 引擎未配置：请安装并注入可用引擎（见 H10 组件清单）")


class RapidOcrAdapter:
    """RapidOCR（onnxruntime）适配器：pip install rapidocr-onnxruntime。

    Apache-2.0 许可；模型权重随包分发，无需单独下载。
    """

    engine_name = "rapidocr-onnxruntime"

    def __init__(self) -> None:
        self._engine: object | None = None
        self._import_error: str | None = None

    def _load(self) -> object | None:
        if self._engine is not None or self._import_error is not None:
            return self._engine
        try:
            from rapidocr_onnxruntime import RapidOCR  # noqa: F401  # 延迟导入
        except ImportError as exc:
            self._import_error = str(exc)
            return None
        self._engine = RapidOCR()
        return self._engine

    def is_available(self) -> bool:
        return self._load() is not None

    def install_hint(self) -> str:
        if self._import_error is None:
            return ""
        return (
            "OCR 引擎 rapidocr-onnxruntime 未安装，无法识别图片/扫描件；"
            "请执行 pip install rapidocr-onnxruntime 后重试"
        )

    def recognize(self, images: list[bytes]) -> list[str]:
        engine = self._load()
        if engine is None:
            raise RuntimeError(self.install_hint())
        results: list[str] = []
        for image in images:
            import io

            from PIL import Image  # rapidocr 依赖 Pillow，延迟导入

            pil_image = Image.open(io.BytesIO(image))
            output, _ = engine(pil_image)  # type: ignore[operator]
            if not output:
                results.append("")
                continue
            results.append("\n".join(str(item[1]) for item in output))
        return results
