"""H03 Excel 读取：真实 xlsx 文件的行抽取与显式错误。"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from app.tabular_parsing import ExcelReadError, read_excel_rows


def build_xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_reads_real_xlsx_to_string_rows() -> None:
    content = build_xlsx(
        [
            ["项目", "结果", "单位"],
            ["丙氨酸氨基转移酶", 45, "U/L"],
            ["尿蛋白定性", "阴性", None],
            [None, None, None],  # 空行跳过
        ]
    )
    rows = read_excel_rows(content)
    assert rows == [
        {"项目": "丙氨酸氨基转移酶", "结果": "45", "单位": "U/L"},
        {"项目": "尿蛋白定性", "结果": "阴性", "单位": ""},
    ]


def test_numeric_cells_become_plain_strings() -> None:
    content = build_xlsx([["项目", "结果"], ["血糖", 6.1]])
    rows = read_excel_rows(content)
    assert rows[0]["结果"] == "6.1"


def test_blank_header_column_raises() -> None:
    content = build_xlsx([["项目", "", "单位"], ["ALT", 45, "U/L"]])
    try:
        read_excel_rows(content)
        raise AssertionError("应当抛出 ExcelReadError")
    except ExcelReadError as exc:
        assert "空列" in str(exc)


def test_empty_sheet_raises() -> None:
    content = build_xlsx([[]])
    try:
        read_excel_rows(content)
        raise AssertionError("应当抛出 ExcelReadError")
    except ExcelReadError as exc:
        assert "为空" in str(exc)


def test_corrupt_content_raises_explicit_error() -> None:
    try:
        read_excel_rows(b"not-an-excel-file")
        raise AssertionError("应当抛出 ExcelReadError")
    except ExcelReadError as exc:
        assert "无法读取" in str(exc)


def test_sheet_index_out_of_range_raises() -> None:
    content = build_xlsx([["项目"], ["ALT"]])
    try:
        read_excel_rows(content, sheet_index=5)
        raise AssertionError("应当抛出 ExcelReadError")
    except ExcelReadError as exc:
        assert "超出范围" in str(exc)
