"""可编辑字段白名单、单位登记与一致性校验。

模型只能提出本文件登记过的动作与字段；未登记内容一律拒绝，
不允许模型直接执行 SQL、任意代码或工具。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: str  # date | int | number | bool | choice
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    options: tuple[str, ...] = ()
    choices_text: tuple[tuple[str, str], ...] = ()
    keywords: tuple[str, ...] = ()

    def describe_range(self) -> str:
        if self.kind == "choice":
            listed = [text for _, text in self.choices_text]
            return "、".join(listed) or "、".join(self.options)
        if self.minimum is None or self.maximum is None:
            return ""
        low = _trim(self.minimum)
        high = _trim(self.maximum)
        unit = f" {self.unit}" if self.unit else ""
        return f"{low}–{high}{unit}"


def _trim(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


PROFILE_FIELDS: dict[str, FieldSpec] = {
    "sex": FieldSpec("sex", "生理性别", "choice", options=("female", "male"),
                     choices_text=(("female", "女"), ("male", "男")),
                     keywords=("性别", "生理性别")),
    "known_cvd": FieldSpec("known_cvd", "已确诊心血管疾病", "bool",
                           keywords=("心血管病", "心血管疾病", "确诊心血管", "冠心病",
                                     "心梗", "脑卒中")),
    "pregnant": FieldSpec("pregnant", "当前妊娠", "bool", keywords=("妊娠", "怀孕", "孕期")),
    "symptomatic": FieldSpec("symptomatic", "当前不适", "bool",
                             keywords=("当前不适", "症状", "不舒服", "胸痛", "胸闷")),
}

VISIT_FIELDS: dict[str, FieldSpec] = {
    "date": FieldSpec("date", "检查日期", "date", keywords=("检查日期", "体检日期", "报告日期")),
    "age": FieldSpec("age", "检查时年龄", "int", unit="岁", minimum=18, maximum=100,
                     keywords=("年龄",)),
    "sbp": FieldSpec("sbp", "收缩压", "number", unit="mmHg", minimum=60, maximum=260,
                     keywords=("收缩压", "高压")),
    "total_c": FieldSpec("total_c", "总胆固醇", "number", minimum=0, maximum=600,
                         keywords=("总胆固醇", "胆固醇")),
    "hdl_c": FieldSpec("hdl_c", "HDL 胆固醇", "number", minimum=0, maximum=200,
                       keywords=("高密度", "hdl")),
    "chol_unit": FieldSpec("chol_unit", "胆固醇单位", "choice",
                           options=("mmol/L", "mg/dL"),
                           choices_text=(("mmol/L", "mmol/L"), ("mg/dL", "mg/dL")),
                           keywords=("胆固醇单位", "单位")),
    "bmi": FieldSpec("bmi", "BMI", "number", unit="kg/m²", minimum=10, maximum=70,
                     keywords=("bmi", "体重指数")),
    "egfr": FieldSpec("egfr", "eGFR", "number", unit="mL/min/1.73m²", minimum=0, maximum=200,
                      keywords=("egfr", "肾小球", "肾功能")),
    "dm": FieldSpec("dm", "糖尿病病史", "bool", keywords=("糖尿病", "糖代谢")),
    "smoking": FieldSpec("smoking", "当前吸烟", "bool", keywords=("吸烟", "抽烟", "戒烟")),
    "bp_tx": FieldSpec("bp_tx", "使用降压药", "bool", keywords=("降压药", "降压治疗")),
    "statin": FieldSpec("statin", "使用他汀", "bool", keywords=("他汀", "降脂药")),
    "hba1c": FieldSpec("hba1c", "HbA1c", "number", unit="%", minimum=3, maximum=20,
                       keywords=("糖化血红蛋白", "hba1c", "糖化")),
    "fasting_glucose": FieldSpec("fasting_glucose", "空腹血糖", "number", unit="mmol/L",
                                 minimum=1, maximum=40, keywords=("空腹血糖", "血糖")),
    "glucose_status": FieldSpec("glucose_status", "既有血糖结论", "choice",
                                options=("normal", "prediabetes", "diabetes", "unknown"),
                                choices_text=(("normal", "正常"), ("prediabetes", "糖尿病前期"),
                                              ("diabetes", "糖尿病"), ("unknown", "未确认")),
                                keywords=("血糖结论", "血糖状态")),
}

# 确认前必须补齐的必填项；缺失时保持未知，不默认“否”。
PROFILE_REQUIRED = ("sex", "known_cvd", "pregnant", "symptomatic")
VISIT_REQUIRED = ("date", "age", "sbp", "total_c", "hdl_c", "bmi", "egfr", "dm", "smoking",
                  "bp_tx", "statin")
# 可选字段缺失不阻塞已有可用能力。
VISIT_OPTIONAL = ("hba1c", "fasting_glucose", "glucose_status")

# 点亮规则使用的字段（“有资料”）。
SYSTEM_FIELDS: dict[str, tuple[str, ...]] = {
    "cardiovascular": ("sbp", "total_c", "hdl_c", "bmi"),
    "glucose_metabolism": ("fasting_glucose", "hba1c", "glucose_status"),
    "renal": ("egfr",),
}
SYSTEM_LABELS = {
    "cardiovascular": "心血管",
    "glucose_metabolism": "血糖与代谢",
    "renal": "肾功能",
}

# 单位登记：只在给出单位与记录单位不同时换算一次，换算后以目标单位存储。
# 1 mmol/L 胆固醇 = 38.67 mg/dL；1 mmol/L 葡萄糖 = 18.0182 mg/dL（平台登记值）。
UNIT_FACTORS: dict[tuple[str, str], float] = {
    ("total_c", "mg/dL"): 0.02586,
    ("total_c", "mmol/L"): 38.67,
    ("hdl_c", "mg/dL"): 0.02586,
    ("hdl_c", "mmol/L"): 38.67,
    ("fasting_glucose", "mg/dL"): 1 / 18.0182,
    ("fasting_glucose", "mmol/L"): 18.0182,
}
UNIT_SOURCE = "平台单位登记值（胆固醇 1 mmol/L=38.67 mg/dL，葡萄糖 1 mmol/L=18.0182 mg/dL）"
ALLOWED_UNITS: dict[str, tuple[str, ...]] = {
    "total_c": ("mmol/L", "mg/dL"),
    "hdl_c": ("mmol/L", "mg/dL"),
    "fasting_glucose": ("mmol/L", "mg/dL"),
}
# 合理区间（按单位）：用于单位标签纠正后的数值一致性检查，不参与医学结论。
PLAUSIBLE_RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("total_c", "mmol/L"): (1.0, 15.5),
    ("total_c", "mg/dL"): (40.0, 600.0),
    ("hdl_c", "mmol/L"): (0.2, 5.0),
    ("hdl_c", "mg/dL"): (8.0, 200.0),
    ("fasting_glucose", "mmol/L"): (1.0, 40.0),
    ("fasting_glucose", "mg/dL"): (18.0, 720.0),
}
CHOLESTEROL_FIELDS = ("total_c", "hdl_c")


def spec_for(field_name: str) -> FieldSpec | None:
    return VISIT_FIELDS.get(field_name) or PROFILE_FIELDS.get(field_name)


def unit_of(field_name: str, visit: dict) -> str | None:
    if field_name in CHOLESTEROL_FIELDS:
        return visit.get("chol_unit") or "mmol/L"
    spec = VISIT_FIELDS.get(field_name)
    return spec.unit if spec else None


def convert_value(field_name: str, value: float, from_unit: str,
                  to_unit: str) -> tuple[float, str] | None:
    """单位换算：返回换算后的数值与依据；无登记换算时返回 None。"""
    if from_unit == to_unit:
        return value, UNIT_SOURCE
    factor = UNIT_FACTORS.get((field_name, from_unit))
    if factor is None:
        return None
    converted = round(float(value) * factor, 3)
    basis = (f"{from_unit} → {to_unit} 换算一次：{value} × {factor} = {converted}；"
             f"{UNIT_SOURCE}")
    return converted, basis


def plausible(field_name: str, value: float, unit: str | None) -> bool:
    if unit is None:
        return True
    bounds = PLAUSIBLE_RANGES.get((field_name, unit))
    if bounds is None:
        return True
    return bounds[0] <= float(value) <= bounds[1]


def validate_field_value(field_name: str, value: object,
                         visit: dict | None = None) -> tuple[bool, str]:
    """白名单字段的类型/范围校验；返回 (是否通过, 说明)。"""
    spec = spec_for(field_name)
    if spec is None:
        return False, f"不支持的字段：{field_name}"
    visit = visit or {}
    if field_name == "date":
        ok = isinstance(value, date)
        return (ok, "" if ok else "检查日期必须是 YYYY-MM-DD")
    if spec.kind == "bool":
        ok = isinstance(value, bool)
        return (ok, "" if ok else f"{spec.label}必须是“是/否/不知道”之一")
    if spec.kind == "choice":
        ok = isinstance(value, str) and value in spec.options
        return (ok, "" if ok else f"{spec.label}只能是：{'、'.join(spec.options)}")
    if spec.kind in ("number", "int"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, f"{spec.label}必须是数字"
        if spec.kind == "int" and not float(value).is_integer():
            return False, f"{spec.label}必须是整数"
        low = spec.minimum if spec.minimum is not None else float("-inf")
        high = spec.maximum if spec.maximum is not None else float("inf")
        if not low <= float(value) <= high:
            return False, f"{spec.label} {value} 超出可接受范围 {spec.describe_range()}"
        return True, ""
    return False, f"不支持的字段类型：{field_name}"


def visit_payload(visit: dict) -> dict:
    """去掉内部字段后的可校验资料（供 PreventionRequest 使用）。"""
    payload = {key: visit.get(key) for key in VISIT_FIELDS}
    payload["date"] = day_of(visit)
    payload["chol_unit"] = visit.get("chol_unit") or "mmol/L"
    payload["glucose_status"] = visit.get("glucose_status") or "unknown"
    return payload


def day_of(visit: dict | None) -> date | None:
    """持久化结构中的检查日期统一为 ISO 字符串，读取时还原为 date。"""
    if not visit:
        return None
    value = visit.get("date")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def day_text(visit: dict | None) -> str | None:
    day = day_of(visit)
    return day.isoformat() if day else None


def normalize_visit(visit: dict) -> dict:
    """写入持久化结构前统一格式化：日期用 ISO 字符串，单位/结论用登记默认值。"""
    out = dict(visit)
    out["date"] = day_text(visit)
    out["chol_unit"] = visit.get("chol_unit") or "mmol/L"
    out["glucose_status"] = visit.get("glucose_status") or "unknown"
    return out


