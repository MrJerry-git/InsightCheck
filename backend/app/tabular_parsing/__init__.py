"""CSV/Excel 表格解析与标准化（H03）。

纯计算模块：输入是已经解出的表格行（键为表头），输出保留原值的
标准化条目、逐项错误与待映射队列。CSV 编码/分隔符探测与文件管理属于
T03；本模块只负责"行 → 结构化条目"的标准化，以及 Excel 只读取值。
契约说明见 docs/H_SERIES_SERVICE_CONTRACTS.md 第四节。
"""

from app.tabular_parsing.excel import ExcelReadError, read_excel_rows
from app.tabular_parsing.parser import TabularReportParser
from app.tabular_parsing.schemas import (
    ColumnMap,
    ParsedMetricEntry,
    ParsedTabularReport,
    ParseIssue,
    UnmappedItem,
)

__all__ = [
    "ColumnMap",
    "ExcelReadError",
    "ParsedMetricEntry",
    "ParsedTabularReport",
    "ParseIssue",
    "TabularReportParser",
    "UnmappedItem",
    "read_excel_rows",
]
