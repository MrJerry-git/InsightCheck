"""H03 表格解析 × H01 真实内置字典对接（PR #19 审核要求）。

解析器只依赖 DictionaryLike 协议，这里用 main 已合并的 ExamDictionary
做真实目录验证：确认单位映射、缺失单位待确认与未登记指标入队三条链路
在真实字典内容上同样成立，而不是只在测试桩上成立。
"""

from __future__ import annotations

from app.exam_dictionary import ExamDictionary
from app.tabular_parsing import TabularReportParser


def make_real_parser() -> TabularReportParser:
    return TabularReportParser(ExamDictionary.load_builtin())


def test_real_dictionary_maps_numeric_with_confirmed_unit() -> None:
    parser = make_real_parser()
    report = parser.parse("real.csv", [{"项目": "收缩压", "结果": "128", "单位": "mmHg"}])
    entry = report.entries[0]
    assert entry.status == "mapped"
    assert entry.canonical_code == "8480-6"
    assert entry.canonical_value == 128.0
    assert entry.canonical_unit == "mmHg"
    assert entry.raw_value == "128"


def test_real_dictionary_does_not_invent_unit_when_missing() -> None:
    """真实字典里有量纲指标（收缩压 mmHg）缺单位时不得补齐 mmHg。"""
    parser = make_real_parser()
    report = parser.parse("real.csv", [{"项目": "收缩压", "结果": "128"}])
    entry = report.entries[0]
    assert entry.status == "unit_missing"
    assert entry.canonical_code == "8480-6"
    assert entry.canonical_value is None
    assert entry.canonical_unit is None
    assert entry.raw_value == "128"
    assert entry.unit_confirmation_required is True
    assert any("未提供单位" in i.message for i in report.issues)


def test_real_dictionary_alias_name_is_resolved() -> None:
    parser = make_real_parser()
    report = parser.parse("real.csv", [{"项目": "高压", "结果": "128", "单位": "mmHg"}])
    assert report.entries[0].canonical_code == "8480-6"


def test_real_dictionary_qualitative_value_maps() -> None:
    parser = make_real_parser()
    report = parser.parse("real.csv", [{"项目": "尿蛋白定性", "结果": "阴性"}])
    entry = report.entries[0]
    assert entry.status == "mapped"
    assert entry.qualitative_status == "阴性"


def test_real_dictionary_unknown_metric_keeps_raw_and_queues() -> None:
    parser = make_real_parser()
    report = parser.parse("real.csv", [{"项目": "未登记新指标X", "结果": "3.1", "单位": "ng/mL"}])
    entry = report.entries[0]
    assert entry.status == "unmapped"
    assert entry.raw_value == "3.1" and entry.raw_unit == "ng/mL"
    assert report.unmapped[0].reason == "name_not_registered"
