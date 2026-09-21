"""确定性解析与单位登记的单元测试。"""

from datetime import date

import pytest

from app.services.conversation import fields as F
from app.services.conversation import parser as P

TODAY = date(2026, 9, 21)


@pytest.mark.parametrize("text,expected", [
    ("2025-09-20", date(2025, 9, 20)),
    ("检查日期 2025年9月20日", date(2025, 9, 20)),
    ("2025/09/20", date(2025, 9, 20)),
    ("昨天", date(2026, 9, 20)),
    ("三年一前", None),
    ("2025-02-30", None),
    ("不吸烟", None),
])
def test_parse_date(text, expected):
    assert P.parse_date(text, TODAY) == expected


def test_parse_relative_year():
    assert P.parse_period("去年", TODAY).year == 2025
    assert P.parse_period("前年", TODAY).year == 2024
    assert P.parse_period("三年前", TODAY).year == 2023
    assert P.parse_period("2024 年 9 月", TODAY).month == 9


@pytest.mark.parametrize("text,expected", [
    ("吸烟", True), ("抽了二十年烟", True), ("不吸烟", False), ("已戒", None),
    ("是", True), ("否", False), ("无", False), ("有", True), ("不知道", None),
])
def test_parse_bool(text, expected):
    assert P.parse_bool(text) is expected


def test_unknown_and_commands():
    assert P.is_unknown("不知道") and P.is_unknown("不清楚，没有记录")
    assert P.is_confirmation("确认") and P.is_confirmation("保存")
    assert not P.is_confirmation("是")
    assert P.is_cancellation("算了，不删了")
    assert P.is_undo("撤销刚才的修改")
    assert P.is_delete("删除去年的记录")
    assert P.is_modify("改成 5.8")


def test_field_detection_is_explicit_about_ambiguity():
    assert P.detect_fields("空腹血糖 5.8") == ("fasting_glucose",)
    assert set(P.detect_fields("血糖 5.8")) == {"fasting_glucose", "hba1c"}
    assert P.detect_fields("总胆固醇 5.2") == ("total_c",)
    assert set(P.detect_fields("胆固醇 5.2")) == {"total_c", "hdl_c"}
    assert P.detect_fields("戒烟了吗") == ("smoking",)


def test_value_parsing_per_field_kind():
    assert P.parse_value_text("fasting_glucose", "5.8 mmol/L").value == 5.8
    assert P.parse_value_text("fasting_glucose", "5.8 mmol/L").unit == "mmol/L"
    assert P.parse_value_text("smoking", "不吸烟").value is False
    assert P.parse_value_text("glucose_status", "糖尿病前期").value == "prediabetes"
    assert P.parse_value_text("age", "55").value == 55
    assert P.parse_value_text("age", "55.5").value is None
    assert P.parse_value_text("smoking", "不知道").unknown is True
    assert P.parse_value_text("sbp", "血压正常").value is None


def test_modify_intent_keeps_ambiguity():
    intent = P.parse_modify("改成 5.8", TODAY)
    assert intent.value == 5.8
    assert intent.candidates == ()
    ambiguous = P.parse_modify("两年均有血糖，改成 5.8", TODAY)
    assert set(ambiguous.candidates) == {"fasting_glucose", "hba1c"}
    label = P.parse_modify("单位写错了，是 mg/dL", TODAY)
    assert label.kind == "unit_label" and label.unit == "mg/dL"
    vague = P.parse_modify("单位改成 mg/dL", TODAY)
    assert vague.kind == "unit_ambiguous"


def test_unit_conversion_is_single_step_and_registered():
    value, basis = F.convert_value("total_c", 200.0, "mg/dL", "mmol/L")
    assert value == pytest.approx(5.172)
    assert "换算一次" in basis
    assert F.convert_value("hba1c", 6.0, "%", "mmol/L") is None


def test_plausible_ranges_catch_label_errors():
    assert F.plausible("total_c", 200.0, "mg/dL")
    assert not F.plausible("total_c", 5.2, "mg/dL")
    assert F.plausible("total_c", 5.2, "mmol/L")
    assert not F.plausible("hdl_c", 1.3, "mg/dL")


def test_field_validation_rejects_out_of_range_and_wrong_type():
    assert F.validate_field_value("sbp", 500)[0] is False
    assert F.validate_field_value("sbp", 138)[0] is True
    assert F.validate_field_value("smoking", True)[0] is True
    assert F.validate_field_value("smoking", "yes")[0] is False
    assert F.validate_field_value("glucose_status", "cured")[0] is False
    assert F.validate_field_value("unknown_field", 1)[0] is False


def test_visit_payload_strips_internal_fields_and_keeps_defaults():
    payload = F.visit_payload({"record_id": "v-1", "date": "2025-09-20", "age": 55,
                               "sbp": 138, "total_c": 5.2, "hdl_c": 1.3, "bmi": 26,
                               "egfr": 88, "dm": False, "smoking": False, "bp_tx": False,
                               "statin": False})
    assert payload["date"] == date(2025, 9, 20)
    assert payload["chol_unit"] == "mmol/L"
    assert payload["glucose_status"] == "unknown"
    assert "record_id" not in payload
