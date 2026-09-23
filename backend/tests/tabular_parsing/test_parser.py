"""H03 表格解析：数值/定性/文字、单位换算、逐项错误与待映射队列。"""

from __future__ import annotations

from dataclasses import dataclass

from app.tabular_parsing import (
    ColumnMap,
    ParsedTabularReport,
    TabularReportParser,
)
from app.tabular_parsing.schemas import ENTRY_STATUSES, NON_COMPARABLE_STATUSES


@dataclass(frozen=True)
class FakeConversion:
    from_unit: str
    to_unit: str
    factor: float
    offset: float
    basis: str


@dataclass(frozen=True)
class FakeEntry:
    code: str
    display_name: str
    value_type: str
    standard_unit: str | None = None
    unit_conversions: tuple[FakeConversion, ...] = ()
    qualitative_values: tuple[str, ...] = ()


class FakeDictionary:
    """最小字典桩：只实现 TabularReportParser 需要的 lookup 接口。"""

    def __init__(self, entries: dict[str, FakeEntry]) -> None:
        self._entries = {k.strip().casefold(): v for k, v in entries.items()}

    def lookup(self, raw_name: str):
        return self._entries.get((raw_name or "").strip().casefold())


def make_parser() -> TabularReportParser:
    dictionary = FakeDictionary(
        {
            "丙氨酸氨基转移酶": FakeEntry(
                code="1742-6", display_name="ALT", value_type="numeric", standard_unit="U/L"
            ),
            "血红蛋白": FakeEntry(
                code="718-7",
                display_name="HGB",
                value_type="numeric",
                standard_unit="g/L",
                unit_conversions=(
                    FakeConversion("g/dL", "g/L", 10.0, 0.0, "1 g/dL = 10 g/L"),
                ),
            ),
            "肌酐": FakeEntry(
                code="2160-0",
                display_name="CREA",
                value_type="numeric",
                standard_unit="μmol/L",
                unit_conversions=(
                    FakeConversion("μmol/L", "mg/dL", 0.0113, 0.0, "1 mg/dL = 88.4 μmol/L"),
                ),
            ),
            "尿蛋白定性": FakeEntry(
                code="20454-5",
                display_name="尿蛋白",
                value_type="qualitative",
                qualitative_values=("阴性", "±", "+", "++", "+++", "++++"),
            ),
            "心电图结论": FakeEntry(
                code="IC:M-ECG-CONCLUSION", display_name="ECG", value_type="text"
            ),
            # 无量纲比值：字典未登记标准单位，缺失单位不应被判为待确认
            "某无量纲比值": FakeEntry(
                code="IC:RATIO", display_name="RATIO", value_type="numeric", standard_unit=None
            ),
        }
    )
    return TabularReportParser(dictionary)


def rows_of(*rows: dict[str, str]) -> list[dict[str, str]]:
    headers = ["项目", "结果", "单位", "参考区间", "提示"]
    return [{h: r.get(h, "") for h in headers} for r in rows]


def entry_of(report: ParsedTabularReport, name: str):
    matches = [e for e in report.entries if e.raw_name == name]
    assert len(matches) == 1, f"期望唯一条目 {name}，得到 {len(matches)}"
    return matches[0]


def test_numeric_with_standard_unit_maps_directly() -> None:
    report = make_parser().parse(
        "demo.csv",
        rows_of({"项目": "丙氨酸氨基转移酶", "结果": "45", "单位": "U/L", "参考区间": "9-50"}),
    )
    entry = entry_of(report, "丙氨酸氨基转移酶")
    assert entry.status == "mapped"
    assert entry.canonical_code == "1742-6"
    assert entry.canonical_value == 45.0
    assert entry.canonical_unit == "U/L"
    assert entry.raw_value == "45" and entry.raw_reference == "9-50"
    assert entry.conversion_basis is None


def test_numeric_unit_converts_only_with_registered_basis() -> None:
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "血红蛋白", "结果": "13.5", "单位": "g/dL"})
    )
    entry = entry_of(report, "血红蛋白")
    assert entry.status == "mapped"
    assert entry.canonical_value == 135.0
    assert entry.canonical_unit == "g/L"
    assert entry.conversion_basis == "1 g/dL = 10 g/L"
    assert entry.raw_unit == "g/dL"  # 原值原单位保留


def test_numeric_without_registered_conversion_keeps_original_unit() -> None:
    # 字典只登记 μmol/L→mg/dL，未登记逆向：1.1 mg/dL 不擅自换算
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "肌酐", "结果": "1.1", "单位": "mg/dL"})
    )
    entry = entry_of(report, "肌酐")
    assert entry.status == "unit_unconverted"
    assert entry.canonical_value == 1.1
    assert entry.canonical_unit == "mg/dL"
    assert any(i.severity == "warning" and "无登记换算依据" in i.message for i in report.issues)


def test_unit_symbol_normalization_matches_standard() -> None:
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "丙氨酸氨基转移酶", "结果": "45", "单位": "u/l"})
    )
    entry = entry_of(report, "丙氨酸氨基转移酶")
    assert entry.status == "mapped" and entry.canonical_unit == "U/L"


def test_invalid_numeric_keeps_raw_and_reports_issue() -> None:
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "丙氨酸氨基转移酶", "结果": "复查", "单位": "U/L"})
    )
    entry = entry_of(report, "丙氨酸氨基转移酶")
    assert entry.status == "invalid_value"
    assert entry.raw_value == "复查" and entry.text_value == "复查"
    assert any(i.severity == "error" and "无法解析" in i.message for i in report.issues)


def test_thousands_separator_numeric_is_accepted() -> None:
    report = make_parser().parse(
        "demo.csv",
        rows_of({"项目": "丙氨酸氨基转移酶", "结果": "1,234", "单位": "U/L"}),
    )
    entry = entry_of(report, "丙氨酸氨基转移酶")
    assert entry.status == "mapped" and entry.canonical_value == 1234.0


def test_qualitative_registered_value_maps() -> None:
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "尿蛋白定性", "结果": "++", "提示": "↑"})
    )
    entry = entry_of(report, "尿蛋白定性")
    assert entry.status == "mapped"
    assert entry.qualitative_status == "++"
    assert entry.report_hint == "↑"  # 原报告标记保留，但不参与判定


def test_qualitative_unregistered_value_keeps_raw_and_queues() -> None:
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "尿蛋白定性", "结果": "弱阳性"})
    )
    entry = entry_of(report, "尿蛋白定性")
    assert entry.status == "unregistered_qualitative"
    assert entry.text_value == "弱阳性"
    assert report.unmapped[0].reason == "qualitative_value_not_registered"
    assert report.unmapped[0].raw_value == "弱阳性"


def test_text_value_passes_through() -> None:
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "心电图结论", "结果": "窦性心律，未见明显异常"})
    )
    entry = entry_of(report, "心电图结论")
    assert entry.status == "mapped"
    assert entry.value_type == "text"
    assert entry.text_value == "窦性心律，未见明显异常"
    assert entry.canonical_value is None


def test_unknown_metric_is_queued_not_dropped() -> None:
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "血浆D-二聚体", "结果": "0.4", "单位": "mg/L"})
    )
    entry = entry_of(report, "血浆D-二聚体")
    assert entry.status == "unmapped"
    assert entry.canonical_code is None
    assert entry.raw_value == "0.4" and entry.raw_unit == "mg/L"
    assert report.unmapped[0].raw_name == "血浆D-二聚体"
    assert report.unmapped[0].reason == "name_not_registered"
    assert any(i.severity == "info" and "未登记指标" in i.message for i in report.issues)


def test_empty_name_with_result_is_row_error() -> None:
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "", "结果": "123", "单位": "U/L"})
    )
    assert report.entries == []
    assert any(i.field == "项目" and i.message == "项目名称为空" for i in report.issues)


def test_blank_rows_are_skipped_silently() -> None:
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "", "结果": ""}, {"项目": "心电图结论", "结果": "正常"})
    )
    assert len(report.entries) == 1
    assert report.issues == []


def test_missing_header_reports_issue_without_entries() -> None:
    report = make_parser().parse("demo.csv", [{"foo": "1", "bar": "2"}])
    assert report.entries == []
    assert any(i.field == "header" for i in report.issues)


def test_variant_headers_are_recognized() -> None:
    rows = [{"名称": "丙氨酸氨基转移酶", "测定值": "45", "单位": "U/L", "参考范围": "9-50"}]
    report = make_parser().parse("demo.csv", rows)
    entry = entry_of(report, "丙氨酸氨基转移酶")
    assert entry.status == "mapped" and entry.canonical_value == 45.0
    assert entry.raw_reference == "9-50"


def test_custom_column_map_override() -> None:
    parser = TabularReportParser(
        FakeDictionary(
            {
                "心电图结论": FakeEntry(
                    code="IC:M-ECG-CONCLUSION", display_name="ECG", value_type="text"
                )
            }
        ),
        columns=ColumnMap(item_names=("检验项目",), result_names=("检验结果",)),
    )
    report = parser.parse("demo.csv", [{"检验项目": "心电图结论", "检验结果": "正常心电图"}])
    assert entry_of(report, "心电图结论").status == "mapped"


def test_page_hint_column_preserved_for_calibration() -> None:
    rows = [{"项目": "丙氨酸氨基转移酶", "结果": "45", "单位": "U/L", "页码": "3"}]
    report = make_parser().parse("demo.csv", rows)
    assert entry_of(report, "丙氨酸氨基转移酶").page_hint == "3"


def test_entries_sorted_deterministically() -> None:
    report = make_parser().parse(
        "demo.csv",
        rows_of(
            {"项目": "心电图结论", "结果": "正常"},
            {"项目": "丙氨酸氨基转移酶", "结果": "45", "单位": "U/L"},
        ),
    )
    assert [e.row_index for e in report.entries] == [1, 2]


# ---- PR #19 审核 P1：缺失/空白单位不得自动赋予标准单位 ----


def test_numeric_without_unit_column_is_pending_confirmation() -> None:
    """复现审核场景：血红蛋白=13.5 且未提供单位，不得返回 g/L / mapped。"""
    report = make_parser().parse("demo.csv", [{"项目": "血红蛋白", "结果": "13.5"}])
    entry = entry_of(report, "血红蛋白")
    assert entry.status == "unit_missing"
    assert entry.canonical_value is None, "缺单位时不能生成可比较数值"
    assert entry.canonical_unit is None, "缺单位时不能赋予标准单位"
    assert entry.raw_value == "13.5" and entry.raw_unit is None
    assert entry.unit_confirmation_required is True
    assert entry.as_dict()["unit_confirmation_required"] is True
    assert any(
        i.severity == "warning" and "未提供单位" in i.message and "g/L" in i.message
        for i in report.issues
    )


def test_numeric_with_empty_unit_is_pending_confirmation() -> None:
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "血红蛋白", "结果": "13.5", "单位": ""})
    )
    entry = entry_of(report, "血红蛋白")
    assert entry.status == "unit_missing"
    assert entry.canonical_value is None and entry.canonical_unit is None
    assert entry.unit_confirmation_required is True


def test_numeric_with_blank_unit_is_pending_confirmation() -> None:
    report = make_parser().parse(
        "demo.csv", rows_of({"项目": "血红蛋白", "结果": "13.5", "单位": "   "})
    )
    entry = entry_of(report, "血红蛋白")
    assert entry.status == "unit_missing"
    assert entry.canonical_value is None and entry.canonical_unit is None


def test_dimensionless_metric_without_unit_still_maps() -> None:
    """字典未登记标准单位（无量纲）：不需要单位确认，按原值映射。"""
    report = make_parser().parse("demo.csv", [{"项目": "某无量纲比值", "结果": "0.86"}])
    entry = entry_of(report, "某无量纲比值")
    assert entry.status == "mapped"
    assert entry.canonical_value == 0.86
    assert entry.unit_confirmation_required is False
    assert report.issues == []


def test_confirmed_unit_still_converts_and_maps() -> None:
    """单位确认或有登记依据时，仍应生成可比较值（不能被新规则误伤）。"""
    direct = make_parser().parse(
        "demo.csv", rows_of({"项目": "血红蛋白", "结果": "135", "单位": "g/L"})
    )
    assert entry_of(direct, "血红蛋白").status == "mapped"
    assert entry_of(direct, "血红蛋白").canonical_unit == "g/L"

    converted = make_parser().parse(
        "demo.csv", rows_of({"项目": "血红蛋白", "结果": "13.5", "单位": "g/dL"})
    )
    assert entry_of(converted, "血红蛋白").canonical_value == 135.0
    assert entry_of(converted, "血红蛋白").conversion_basis == "1 g/dL = 10 g/L"


def test_unit_missing_is_not_comparable_for_downstream() -> None:
    """下游（H05 趋势 / H07 规则）据此判定不可比较。"""
    assert "unit_missing" in ENTRY_STATUSES
    assert "unit_missing" in NON_COMPARABLE_STATUSES
    assert "unit_unconverted" in NON_COMPARABLE_STATUSES
