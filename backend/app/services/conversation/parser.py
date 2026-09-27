"""追问回答与用户指令的确定性解析（模型只作兜底）。

解析失败时返回 None，由调用方决定继续追问或回退模型；
任何一条规则都不会把“未提及”当作“否”。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.services.conversation import fields as F

_FULL_DATE_RES = (
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})[日号]?"),
    re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"),
    re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})"),
)
_YEAR_RE = re.compile(r"(\d{4})年")
_RELATIVE_DAYS = {"今天": 0, "今日": 0, "昨天": 1, "昨日": 1, "前天": 2}
_RELATIVE_YEARS = {"明年": -1, "今年": 0, "本年": 0, "去年": 1, "上年": 1, "前年": 2}
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_NUMBER_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d])")
_CN_YEARS_AGO_RE = re.compile(r"([零〇一两二三四五六七八九十]{1,3})\s*年前")
_UNIT_PATTERNS = (
    ("mmhg", "mmHg"), ("mmol/l", "mmol/L"), ("mmol", "mmol/L"), ("mg/dl", "mg/dL"),
    ("mgdl", "mg/dL"), ("kg/m2", "kg/m²"), ("kg/m²", "kg/m²"), ("%", "%"),
    ("ml/min", "mL/min/1.73m²"),
)
_UNKNOWN_TEXTS = ("不知道", "不清楚", "不记得", "不详", "说不清", "忘了", "不确定",
                  "没有记录", "没记录", "没测过", "未测", "说不上")
_TRUE_TEXTS = ("是的", "是", "有", "正在用", "在吃", "在用", "有在吃", "服用", "使用",
               "阳性", "确诊", "吸", "抽", "用过", "有的", "对的", "有服药", "有在用")
_FALSE_TEXTS = ("不吸烟", "不抽烟", "没吸", "未吸", "不吸", "否", "没有", "无", "未使用",
                "未用", "没用", "没吃", "未服用", "不吃", "阴性", "从未", "从来没",
                "均无", "都没有", "没在用", "未在", "不用")
_CONFIRM_TEXTS = ("确认", "确定保存", "保存", "可以了", "没问题", "就这样", "对了",
                  "没有补充", "补充完毕", "无误", "正确")
_CANCEL_TEXTS = ("算了", "取消", "不删了", "不用了", "先不", "别删", "不要删", "不做")
_UNDO_TEXTS = ("撤销", "撤回", "恢复上一步", "退回", "反悔", "取消刚才", "取消上一步",
               "还原最近")
_DELETE_TEXTS = ("删除", "删掉", "删了", "去掉", "移除", "清除", "抹掉")
_MODIFY_TEXTS = ("改成", "改为", "修改", "更正", "订正", "调整为", "变成", "写成", "应为",
                 "应该是", "修改为")
_UNIT_AMBIGUITY_TEXTS = ("单位", "单位写错", "单位不对", "单位错了")


@dataclass
class ModifyIntent:
    candidates: tuple[str, ...] = ()
    value: object = None
    unit: str | None = None
    kind: str = "value"  # value | unit_label | unit_ambiguous
    day: date | None = None
    year: int | None = None
    month: int | None = None
    record_id: str | None = None
    raw: str = ""

    def has_value(self) -> bool:
        return self.value is not None


@dataclass
class DeleteIntent:
    day: date | None = None
    year: int | None = None
    month: int | None = None
    record_id: str | None = None
    candidates: tuple[str, ...] = ()
    raw: str = ""


@dataclass
class ReadPeriod:
    year: int | None = None
    month: int | None = None
    day: date | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ParsedValue:
    """字段值解析结果：unknown 表示用户明确表达“不知道”。"""

    value: object = None
    unit: str | None = None
    unknown: bool = False


def parse_value_text(field_name: str, text: str | None, unit: str | None = None,
                     today: date | None = None) -> ParsedValue:
    spec = F.spec_for(field_name)
    raw = (text or "").strip()
    if spec is None or not raw:
        return ParsedValue()
    if is_unknown(raw):
        return ParsedValue(unknown=True)
    if spec.kind == "date":
        return ParsedValue(parse_date(raw, today))
    if spec.kind == "bool":
        return ParsedValue(parse_bool(raw))
    if spec.kind == "choice":
        return ParsedValue(parse_choice(raw, field_name))
    number = parse_number(raw)
    if number is None:
        return ParsedValue()
    if spec.kind == "int":
        if not float(number).is_integer():
            return ParsedValue()
        number = int(number)
    return ParsedValue(number, unit or parse_unit(raw))


def _cn_to_int(text: str) -> int | None:
    if not text:
        return None
    if text in _CN_DIGITS:
        return _CN_DIGITS[text]
    if text.startswith("十"):
        return 10 + _CN_DIGITS.get(text[1:], 0)
    if text.endswith("十"):
        return _CN_DIGITS.get(text[:-1], 0) * 10
    if "十" in text:
        left, _, right = text.partition("十")
        return _CN_DIGITS.get(left, 0) * 10 + _CN_DIGITS.get(right, 0)
    return None


def parse_date(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    lowered = text.lower()
    for pattern in _FULL_DATE_RES:
        match = pattern.search(lowered)
        if match:
            year, month, day = (int(part) for part in match.groups())
            try:
                return date(year, month, day)
            except ValueError:
                return None
    for word, delta in _RELATIVE_DAYS.items():
        if word in text:
            return date.fromordinal(today.toordinal() - delta)
    years_ago = _CN_YEARS_AGO_RE.search(text)
    if years_ago:
        amount = _cn_to_int(years_ago.group(1))
        if amount:
            return _shift_years(today, amount)
    for word, amount in _RELATIVE_YEARS.items():
        if word in text:
            target = _shift_years(today, amount)
            month = re.search(r"(\d{1,2})月", text)
            if month:
                day = re.search(r"(\d{1,2})[日号]", text)
                return date(target.year, int(month.group(1)),
                            int(day.group(1)) if day else 1)
            return None
    return None


def parse_period(text: str, today: date | None = None) -> ReadPeriod | None:
    """定位记录用的年份/月份（如“去年的记录”“2025 年 9 月”）。"""
    today = today or date.today()
    exact = parse_date(text, today)
    if exact:
        return ReadPeriod(year=exact.year, month=exact.month, day=exact)
    lowered = text.lower()
    year_match = _YEAR_RE.search(lowered)
    if year_match:
        year = int(year_match.group(1))
    else:
        year = None
        for word, amount in _RELATIVE_YEARS.items():
            if word in text:
                year = _shift_years(today, amount).year
                break
    month_match = re.search(r"(\d{1,2})\s*月", text)
    month = int(month_match.group(1)) if month_match else None
    if month is not None and not 1 <= month <= 12:
        month = None
    if year is None and month is None:
        return None
    return ReadPeriod(year=year, month=month)


def _shift_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def parse_number(text: str) -> float | None:
    without_dates = text
    for pattern in _FULL_DATE_RES:
        without_dates = pattern.sub(" ", without_dates)
    without_dates = _YEAR_RE.sub(" ", without_dates)
    match = _NUMBER_RE.search(without_dates)
    return float(match.group(1)) if match else None


def parse_unit(text: str) -> str | None:
    lowered = text.lower()
    for needle, unit in _UNIT_PATTERNS:
        if needle in lowered:
            return unit
    return None


def is_unknown(text: str) -> bool:
    return any(word in text for word in _UNKNOWN_TEXTS)


def parse_bool(text: str) -> bool | None:
    stripped = text.strip()
    for word in _FALSE_TEXTS:
        if word in stripped:
            return False
    for word in _TRUE_TEXTS:
        if word in stripped:
            return True
    return None


def parse_choice(text: str, field_name: str) -> str | None:
    spec = F.spec_for(field_name)
    if spec is None or spec.kind != "choice":
        return None
    if field_name == "glucose_status":
        ordering = (("糖尿病前期", "prediabetes"), ("前期", "prediabetes"),
                    ("糖尿病", "diabetes"), ("确诊", "diabetes"), ("正常", "normal"),
                    ("没问题", "normal"), ("未确认", "unknown"))
        for needle, value in ordering:
            if needle in text:
                return value
        return None
    lowered = text.lower()
    for value, label in spec.choices_text:
        if label.lower() in lowered or value.lower() in lowered:
            return value
    return None


def is_confirmation(text: str) -> bool:
    stripped = text.strip().rstrip("。.!！~ ")
    if not stripped:
        return False
    if is_unknown(stripped) or parse_bool(stripped) is False:
        return False
    if stripped in _CONFIRM_TEXTS:
        return True
    return any(stripped.startswith(word) and len(stripped) <= len(word) + 4
               for word in _CONFIRM_TEXTS)


def is_cancellation(text: str) -> bool:
    stripped = text.strip()
    return any(word in stripped for word in _CANCEL_TEXTS)


def is_undo(text: str) -> bool:
    stripped = text.strip()
    return any(word in stripped for word in _UNDO_TEXTS)


def is_delete(text: str) -> bool:
    stripped = text.strip()
    return any(word in stripped for word in _DELETE_TEXTS)


def is_modify(text: str) -> bool:
    stripped = text.strip()
    return any(word in stripped for word in _MODIFY_TEXTS)


def detect_fields(text: str) -> tuple[str, ...]:
    """返回文本中出现的字段名；血糖/胆固醇泛指时返回多个候选。"""
    lowered = text.lower()
    found: list[str] = []
    if "空腹血糖" in lowered:
        found.append("fasting_glucose")
    if "糖化" in lowered or "hba1c" in lowered:
        found.append("hba1c")
    if "血糖" in lowered and "fasting_glucose" not in found and "hba1c" not in found:
        found.extend(["fasting_glucose", "hba1c"])
    if "总胆固醇" in lowered:
        found.append("total_c")
    if "高密度" in lowered or "hdl" in lowered:
        found.append("hdl_c")
    if "胆固醇" in lowered and "total_c" not in found and "hdl_c" not in found:
        found.extend(["total_c", "hdl_c"])
    for name, spec in {**F.VISIT_FIELDS, **F.PROFILE_FIELDS}.items():
        if name in found:
            continue
        if any(keyword in lowered for keyword in spec.keywords):
            found.append(name)
    return tuple(dict.fromkeys(found))


def detect_record_id(text: str) -> str | None:
    match = re.search(r"\b(v-[0-9a-f]{6,})\b", text.lower())
    return match.group(1) if match else None


def parse_modify(text: str, today: date | None = None) -> ModifyIntent | None:
    if not is_modify(text) and not is_unit_correction(text):
        return None
    intent = ModifyIntent(raw=text)
    intent.record_id = detect_record_id(text)
    period = parse_period(text, today)
    if period:
        intent.day, intent.year, intent.month = period.day, period.year, period.month
    intent.candidates = detect_fields(text)
    intent.unit = parse_unit(text)
    if is_unit_correction(text):
        intent.kind = "unit_label" if _explicit_unit_label(text) else "unit_ambiguous"
        intent.candidates = ("chol_unit",)
        intent.value = intent.unit
        return intent
    if intent.candidates == ("chol_unit",) and intent.unit:
        intent.kind = "unit_ambiguous"
        intent.value = intent.unit
        return intent
    if intent.candidates == ("date",):
        # 日期可能不合法（如 2025-02-30）：保留意图，由执行器解释原因并保留原记录。
        intent.value = parse_date(text, today)
        return intent
    value = parse_number(text)
    if value is not None:
        intent.value = float(value)
        spec = F.spec_for(intent.candidates[0]) if len(intent.candidates) == 1 else None
        if spec and spec.kind == "int":
            intent.value = int(value)
    elif intent.unit and any(name in intent.candidates
                             for name in ("chol_unit",)):
        intent.kind = "unit_ambiguous"
        intent.value = intent.unit
    elif (len(intent.candidates) == 1
          and F.spec_for(intent.candidates[0]).kind in ("bool", "choice")):
        parsed = (parse_choice(text, intent.candidates[0])
                  if F.spec_for(intent.candidates[0]).kind == "choice"
                  else parse_bool(text))
        if parsed is None:
            return None
        intent.value = parsed
    else:
        return None
    return intent


def is_unit_correction(text: str) -> bool:
    """只有明确表达“纠正单位/换算”意图时才算单位操作，避免把资料正文误判为指令。"""
    lowered = text.lower()
    if "单位" not in lowered and "换算" not in lowered:
        return False
    intent_words = (*_MODIFY_TEXTS, "写错", "错", "不对", "标签", "纠正", "换算", "抄错")
    if not any(word in lowered for word in intent_words):
        return False
    return parse_unit(text) is not None or any(word in lowered
                                               for word in _UNIT_AMBIGUITY_TEXTS)


def _explicit_unit_label(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ("单位写错", "单位不对", "单位错了", "标签", "抄错"))


def parse_delete(text: str, today: date | None = None) -> DeleteIntent | None:
    if not is_delete(text):
        return None
    intent = DeleteIntent(raw=text)
    intent.record_id = detect_record_id(text)
    period = parse_period(text, today)
    if period:
        intent.day, intent.year, intent.month = period.day, period.year, period.month
    return intent


def relative_hint(text: str) -> str:
    """生成“未定时间”的安全提示文案，不编造日期。"""
    period = parse_period(text)
    if period and period.year:
        if period.month:
            return f"{period.year} 年 {period.month} 月"
        return f"{period.year} 年"
    return "你指定的范围"
