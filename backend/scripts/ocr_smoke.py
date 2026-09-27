"""生成 H04 OCR 实际运行记录（PR #20 审核要求）。

用法：
    python backend/scripts/ocr_smoke.py

依赖（未安装时脚本会明确报错，不生成伪造记录）：
    pip install -e '.[ocr]'      # pypdfium2（渲染）+ rapidocr-onnxruntime（OCR）

脚本构造三类真实样例 PDF（全扫描 2 页、文字+扫描混合、文字+扫描+空白三页），
用真实渲染器与 OCR 引擎执行逐页抽取，把版本、样例、结果写入
docs/ocr-run-record.json，供人工核对与回归比对。

样例 PDF 由 Pillow + 手写 PDF 结构现场构造，**不依赖 PyMuPDF/fitz**：
图片页以 FlateDecode 原始 RGB 嵌入，天然无文本层，等价扫描件。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import sys
import time
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.report_extraction import (  # noqa: E402
    RapidOcrAdapter,
    ReportTextExtractor,
    default_renderer,
)

GROUND_TRUTH = [
    "Total Cholesterol 5.2 mmol/L",
    "Fasting Glucose 6.1 mmol/L",
]
# 中文报告样例（PR #20 复核要求补充中文报告 OCR 样例）
SCAN_ZH_TRUTH = [
    "血常规检验报告",
    "血红蛋白 135 g/L",
    "空腹血糖 5.2 mmol/L",
]

# 系统中文字体候选：找不到时中文样例被显式跳过，不伪造记录
_CJK_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


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


# ---- 手写 PDF 结构（不依赖 fitz）----


def _content_stream(lines: list[str]) -> bytes:
    parts = ["BT", "/F1 12 Tf", "14 TL", "1 0 0 1 72 750 Tm"]
    for index, line in enumerate(lines):
        if index > 0:
            parts.append("T*")
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        parts.append(f"({escaped}) Tj")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")


def _cjk_font(size: int = 44):
    """加载系统中文字体；找不到返回 None（调用方显式跳过中文样例）。"""
    from PIL import ImageFont

    for path in _CJK_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return None


def _text_image(text: str, width: int = 1000, height: int = 300, font=None):
    """Pillow 画白底黑字图片，供构造"扫描件"（无文本层）。

    ``font`` 为 None 时用 Pillow 默认字体（英文样例）；中文样例传入 CJK 字体。
    """
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    if font is None:
        try:
            font = ImageFont.load_default(size=48)
        except TypeError:  # Pillow < 10.1 无 size 参数
            font = ImageFont.load_default()
    box = draw.multiline_textbbox((0, 0), text, font=font, spacing=28)
    draw.multiline_text(
        (
            (width - (box[2] - box[0])) / 2 - box[0],
            (height - (box[3] - box[1])) / 2 - box[1],
        ),
        text,
        fill="black",
        font=font,
        spacing=28,
    )
    return image


def _append(objects: list[bytes], body: bytes) -> int:
    objects.append(body)
    return len(objects)  # 对象编号（1-based）


def _pdf_stream(payload: bytes) -> bytes:
    return (
        b"<< /Length " + str(len(payload)).encode() + b" >>\nstream\n" + payload + b"\nendstream"
    )


def _pdf_bytes(objects: list[bytes]) -> bytes:
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


def compose_pdf(pages: list[dict]) -> bytes:
    """手工构造多页 PDF：文本页有文本层，图片页无文本层（等价扫描件）。"""
    objects: list[bytes] = [b"", b""]  # 1=Catalog, 2=Pages（稍后回填）
    font_no = _append(objects, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids: list[int] = []
    for page in pages:
        if page["kind"] == "text":
            contents_no = _append(objects, _pdf_stream(_content_stream(page["lines"])))
            kids.append(
                _append(
                    objects,
                    (
                        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                        f"/Resources << /Font << /F1 {font_no} 0 R >> >> "
                        f"/Contents {contents_no} 0 R >>"
                    ).encode(),
                )
            )
        else:
            image = page["image"]
            width, height = image.size
            payload = zlib.compress(image.convert("RGB").tobytes(), 9)
            contents_no = _append(
                objects, _pdf_stream(f"q {width} 0 0 {height} 0 0 cm /Im0 Do Q".encode())
            )
            image_no = _append(
                objects,
                (
                    f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
                    f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
                    f"/Length {len(payload)} >>\nstream\n"
                ).encode()
                + payload
                + b"\nendstream",
            )
            kids.append(
                _append(
                    objects,
                    (
                        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
                        f"/Resources << /XObject << /Im0 {image_no} 0 R >> >> "
                        f"/Contents {contents_no} 0 R >>"
                    ).encode(),
                )
            )
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{no} 0 R".encode() for no in kids)
        + b"] /Count "
        + str(len(kids)).encode()
        + b" >>"
    )
    return _pdf_bytes(objects)


def _scanned_page(text: str | None = None, font=None, height: int = 300) -> dict:
    """构造一个无文本层的扫描页（图片页）。

    ``text`` 缺省为英文真值两行；中文样例传入 ``font=_cjk_font()`` 与中文文本。
    """
    body = "\n".join(GROUND_TRUTH) if text is None else text
    return {
        "kind": "image",
        "image": _text_image(body, width=1000, height=height, font=font),
    }


def run_case(extractor: ReportTextExtractor, name: str, content: bytes) -> dict:
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
    renderer = default_renderer()
    if not ocr.is_available() or not renderer.is_available():
        hint = ocr.install_hint() or getattr(renderer, "install_hint", lambda: "")()
        print("OCR 环境不可用，未生成运行记录：", hint)
        return 1

    extractor = ReportTextExtractor(ocr_engine=ocr, pdf_renderer=renderer)

    scan_bytes = compose_pdf([_scanned_page(), _scanned_page()])
    mixed_bytes = compose_pdf(
        [
            {"kind": "text", "lines": ["Lab Report WBC 6.2 10*9/L 3.5-9.5"]},
            _scanned_page(),
        ]
    )
    multi_bytes = compose_pdf(
        [
            {"kind": "text", "lines": ["Page one text layer"]},
            _scanned_page(),
            {"kind": "image", "image": _text_image("")},  # 空白图页：应显式 failed
        ]
    )

    cjk_font = _cjk_font()
    zh_bytes = (
        compose_pdf([_scanned_page("\n".join(SCAN_ZH_TRUTH), font=cjk_font, height=420)])
        if cjk_font is not None
        else None
    )

    cases = [
        run_case(extractor, "scan_2p.pdf", scan_bytes),
        run_case(extractor, "mixed.pdf", mixed_bytes),
        run_case(extractor, "multi_3p.pdf", multi_bytes),
    ]
    if zh_bytes is not None:
        cases.append(run_case(extractor, "scan_zh.pdf", zh_bytes))

    record = {
        "generated_at_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "ocr_engine": ocr.engine_name,
            "pdf_renderer": renderer.renderer_name,
            "versions": {
                "pypdfium2": _version("pypdfium2"),
                "rapidocr_onnxruntime": _version("rapidocr_onnxruntime"),
                "pypdf": _version("pypdf"),
            },
        },
        "ground_truth": GROUND_TRUTH,
        "ground_truth_zh": SCAN_ZH_TRUTH,
        "notes": (
            "中文样例因未找到系统中文字体而跳过" if zh_bytes is None else "中文样例已包含"
        ),
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
