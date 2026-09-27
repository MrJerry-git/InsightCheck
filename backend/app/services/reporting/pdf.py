"""T09：不依赖外部库的中文 PDF 生成。

使用 PDF 标准 CJK 字体 ``STSong-Light`` + ``UniGB-UCS2-H`` 编码，正文按
UTF-16BE 十六进制字符串写入：常见阅读器（Preview、Acrobat、Chrome）都能显示中文，
无需随包分发字体文件。生成内容只来自已保存的方案快照，不做二次计算。
"""

from __future__ import annotations

from dataclasses import dataclass, field

PAGE_WIDTH = 595  # A4 pt
PAGE_HEIGHT = 842
MARGIN_X = 50
MARGIN_TOP = 60
MARGIN_BOTTOM = 60
LINE_HEIGHT = 18
TITLE_SIZE = 16
BODY_SIZE = 11
MAX_CHARS_PER_LINE = 42


@dataclass
class PdfPage:
    lines: list[tuple[str, int]] = field(default_factory=list)


def wrap(text: str, limit: int = MAX_CHARS_PER_LINE) -> list[str]:
    """按字符宽度粗略折行；中文与西文混排时优先在空格处断开。"""

    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for char in text:
        current += char
        if len(current) >= limit and (char in " ，。；、,;)" or len(current) >= limit + 8):
            lines.append(current.rstrip())
            current = ""
    if current:
        lines.append(current.rstrip())
    return lines or [""]


def escape_text(text: str) -> str:
    """PDF 十六进制字符串只需要字节，不做括号转义；这里保留供调用方检查。"""

    return text.replace("\r", " ").replace("\n", " ")


def hex_text(text: str) -> str:
    return "<" + text.encode("utf-16-be").hex().upper() + ">"


class SimpleChinesePdf:
    """极简 PDF 文档：每页若干行文本，使用标准 CJK 字体。"""

    def __init__(self) -> None:
        self.pages: list[PdfPage] = [PdfPage()]
        self._y = PAGE_HEIGHT - MARGIN_TOP

    def _new_page_if_needed(self) -> None:
        if self._y <= MARGIN_BOTTOM:
            self.pages.append(PdfPage())
            self._y = PAGE_HEIGHT - MARGIN_TOP

    def add_line(self, text: str, *, size: int = BODY_SIZE) -> None:
        for chunk in wrap(escape_text(text)):
            self._new_page_if_needed()
            self.pages[-1].lines.append((chunk, size))
            self._y -= LINE_HEIGHT

    def add_title(self, text: str) -> None:
        self.add_line(text, size=TITLE_SIZE)
        self._y -= 6

    def add_spacer(self, height: int = LINE_HEIGHT) -> None:
        self._y -= height

    def to_bytes(self) -> bytes:
        objects: list[bytes] = []

        def add(body: str | bytes) -> int:
            payload = body.encode("latin-1") if isinstance(body, str) else body
            objects.append(payload)
            return len(objects)

        catalog_id = add("<< /Type /Catalog /Pages 2 0 R >>")
        pages_id = add("PLACEHOLDER")
        font_id = add(
            "<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light "
            "/Encoding /UniGB-UCS2-H /DescendantFonts [4 0 R] >>"
        )
        descendant_id = add(
            "<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> "
            # ASCII 半角宽度，避免拉丁字母与数字被排成全角。
            "/FontDescriptor 5 0 R /DW 1000 /W [ 32 126 500 ] >>"
        )
        descriptor_id = add(
            "<< /Type /FontDescriptor /FontName /STSong-Light /Flags 4 "
            "/FontBBox [0 -200 1000 900] /ItalicAngle 0 /Ascent 880 /Descent -120 "
            "/CapHeight 880 /StemV 93 >>"
        )
        assert (catalog_id, pages_id, font_id, descendant_id, descriptor_id) == (1, 2, 3, 4, 5)

        page_ids: list[int] = []
        for page in self.pages:
            y_position = PAGE_HEIGHT - MARGIN_TOP
            parts = ["BT"]
            for line, size in page.lines:
                parts.append(f"/F1 {size} Tf")
                parts.append(f"1 0 0 1 {MARGIN_X} {y_position} Tm")
                parts.append(f"{hex_text(line)} Tj")
                y_position -= LINE_HEIGHT
            parts.append("ET")
            stream = "\n".join(parts).encode("latin-1")
            content_id = add(
                b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream
                + b"\nendstream"
            )
            page_ids.append(
                add(
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
                )
            )

        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode(
            "latin-1"
        )

        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for index, body in enumerate(objects, start=1):
            offsets.append(len(output))
            output.extend(f"{index} 0 obj\n".encode())
            output.extend(body)
            output.extend(b"\nendobj\n")
        xref_offset = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode())
        output.extend(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode()
        )
        return bytes(output)
