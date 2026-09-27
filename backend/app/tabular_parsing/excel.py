"""Excel 只读值读取（openpyxl，read_only 模式，不读样式）。

约定：第一个非空行为表头行；其余行为数据行，全部转为字符串。
合并单元格/空表头会显式报错，不做猜测。
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook


class ExcelReadError(ValueError):
    """Excel 内容无法按约定读取；message 说明具体原因。"""


def read_excel_rows(content: bytes, sheet_index: int = 0) -> list[dict[str, str]]:
    """把 Excel 首个工作表读为 行字典列表（键=表头，值=字符串）。

    空行整行跳过；单元格值 None 转为空字符串。表头行为空或含空表头
    单元格时抛出 ExcelReadError，由调用方转为解析问题，不静默处理。
    """
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl 对坏文件抛多种异常，统一转显式错误
        raise ExcelReadError(f"无法读取 Excel 文件：{exc}") from exc
    try:
        if sheet_index >= len(workbook.sheetnames):
            raise ExcelReadError(
                f"工作表索引 {sheet_index} 超出范围（共 {len(workbook.sheetnames)} 个）"
            )
        sheet = workbook[workbook.sheetnames[sheet_index]]
        matrix: list[list[str]] = []
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if v is None else str(v).strip() for v in row]
            if any(cells):
                matrix.append(cells)
        if not matrix:
            raise ExcelReadError("工作表为空")
        headers = matrix[0]
        if all(not h for h in headers):
            raise ExcelReadError("表头行为空")
        blank_headers = [i + 1 for i, h in enumerate(headers) if not h]
        if blank_headers:
            raise ExcelReadError(f"表头存在空列（列号 {blank_headers}），请补齐或删除空列")
        rows: list[dict[str, str]] = []
        for cells in matrix[1:]:
            padded = cells + [""] * (len(headers) - len(cells))
            rows.append({h: padded[i] for i, h in enumerate(headers)})
        return rows
    finally:
        workbook.close()
