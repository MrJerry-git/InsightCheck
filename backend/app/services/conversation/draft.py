"""草稿结构与缺口计算：未确认资料不点亮人体、不参与规划。"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.services.conversation import fields as F
from app.services.prevent_equations import eligibility

MAX_QUESTIONS = 4


def new_record_id() -> str:
    return "v-" + uuid4().hex[:8]


def new_draft() -> dict:
    return {"sex": None, "known_cvd": None, "pregnant": None, "symptomatic": None,
            "visits": [], "unknowns": [], "warnings": []}


def normalize(data: dict | None) -> dict:
    draft = new_draft()
    if not data:
        return draft
    for key in ("sex", "known_cvd", "pregnant", "symptomatic"):
        draft[key] = data.get(key)
    draft["unknowns"] = list(data.get("unknowns") or [])
    draft["warnings"] = list(data.get("warnings") or [])
    for visit in data.get("visits") or []:
        merged = {"record_id": visit.get("record_id") or new_record_id()}
        for name in F.VISIT_FIELDS:
            merged[name] = visit.get(name)
        draft["visits"].append(merged)
    return draft


def new_visit(day: date | None = None) -> dict:
    visit = {"record_id": new_record_id(), "date": day.isoformat() if day else None}
    for name in F.VISIT_FIELDS:
        if name != "date":
            visit[name] = None
    return visit


def path(record_id: str, name: str) -> str:
    return f"visits.{record_id}.{name}"


def find_records(data: dict, *, record_id: str | None = None, day: date | None = None,
                 year: int | None = None, month: int | None = None,
                 source: str = "draft") -> list[dict]:
    visits = visits_of(data, source)
    if record_id:
        return [v for v in visits if v.get("record_id") == record_id]
    if day:
        return [v for v in visits if F.day_of(v) == day]
    if year is None and month is None:
        return []
    matches = []
    for visit in visits:
        current = F.day_of(visit)
        if current is None:
            continue
        if year is not None and current.year != year:
            continue
        if month is not None and current.month != month:
            continue
        matches.append(visit)
    return matches


def visits_of(data: dict | None, source: str = "draft") -> list[dict]:
    if not data:
        return []
    if source == "confirmed":
        return list(data.get("visits") or [])
    return list(data.get("visits") or [])


def set_unknown(data: dict, record_id: str | None, name: str) -> None:
    target = path(record_id, name) if record_id else name
    unknowns = data.setdefault("unknowns", [])
    if target not in unknowns:
        unknowns.append(target)


def clear_unknown(data: dict, record_id: str | None, name: str) -> None:
    target = path(record_id, name) if record_id else name
    unknowns = [item for item in data.setdefault("unknowns", []) if item != target]
    data["unknowns"] = unknowns


def is_unknown_field(data: dict | None, record_id: str | None, name: str) -> bool:
    if not data:
        return False
    target = path(record_id, name) if record_id else name
    return target in (data.get("unknowns") or [])


def set_field(data: dict, record_id: str | None, name: str, value: object) -> None:
    if isinstance(value, date):
        value = value.isoformat()
    if record_id is None:
        data[name] = value
        clear_unknown(data, None, name)
        return
    for visit in data.get("visits") or []:
        if visit.get("record_id") == record_id:
            visit[name] = value
            clear_unknown(data, record_id, name)
            return
    raise KeyError(record_id)


def required_visit_fields(visit: dict) -> tuple[str, ...]:
    required = list(F.VISIT_REQUIRED)
    if visit.get("total_c") is not None or visit.get("hdl_c") is not None:
        required.append("chol_unit")
    return tuple(required)


def missing_paths(data: dict | None, *, include_unknown: bool = False) -> list[str]:
    """必填缺项（保持未知，不默认“否”）；可选字段缺失不算缺项。"""
    if not data:
        return []
    missing: list[str] = []
    for name in F.PROFILE_REQUIRED:
        if data.get(name) is None and (include_unknown or not is_unknown_field(data, None, name)):
            missing.append(name)
    for visit in data.get("visits") or []:
        record_id = visit.get("record_id")
        for name in required_visit_fields(visit):
            if visit.get(name) is None and (include_unknown
                                            or not is_unknown_field(data, record_id, name)):
                missing.append(path(record_id, name))
    return missing


def unknown_paths(data: dict | None) -> list[str]:
    return list((data or {}).get("unknowns") or [])


_QUESTION_ORDER = ("date", "age", "sex", "sbp", "total_c", "hdl_c", "chol_unit", "bmi",
                   "egfr", "dm", "smoking", "bp_tx", "statin", "known_cvd", "pregnant",
                   "symptomatic")


def question_for(name: str, record_id: str | None, visit: dict | None) -> dict:
    spec = F.spec_for(name)
    label = spec.label if spec else name
    when = ""
    if visit and visit.get("date"):
        when = f"{F.day_text(visit)} 的记录"
    elif visit:
        when = "这条尚未标明日期的记录"
    if spec and spec.kind == "bool":
        prompt = f"{label}？请回答：是 / 否 / 不知道"
    elif spec and spec.kind == "choice":
        prompt = f"{label}？可选：{'、'.join(text for _, text in spec.choices_text)}"
    elif spec and spec.kind == "date":
        prompt = "这次检查的日期是？（格式 YYYY-MM-DD，不知道也可以直接说）"
    elif name == "chol_unit":
        prompt = "胆固醇的单位是 mmol/L 还是 mg/dL？"
    elif spec:
        prompt = f"{label}是多少？（{spec.describe_range()}）"
    else:
        prompt = f"{label}是？"
    question = f"{when}{'，' if when else ''}{prompt}"
    return {"action_id": "q-" + uuid4().hex[:8], "path": path(record_id, name) if record_id
            else name, "field": name, "record_id": record_id, "question": question,
            "kind": "field"}


def questions_for(data: dict | None, limit: int = MAX_QUESTIONS) -> list[dict]:
    if not data:
        return []
    pending = missing_paths(data)
    if not pending:
        return []
    entries: list[tuple[int, dict]] = []
    for item in pending:
        record_id: str | None = None
        name = item
        if item.startswith("visits."):
            _, record_id, name = item.split(".", 2)
        visit = next((v for v in data.get("visits") or []
                      if v.get("record_id") == record_id), None)
        order = _QUESTION_ORDER.index(name) if name in _QUESTION_ORDER else len(_QUESTION_ORDER)
        if record_id:
            order += 1
        entries.append((order, question_for(name, record_id, visit)))
    entries.sort(key=lambda pair: pair[0])
    return [item for _, item in entries[:limit]]


def system_detail(confirmed: dict | None, as_of: date | None = None) -> dict[str, dict]:
    """区分“有资料”（点亮）与“可以计算”（可执行评估）。"""
    as_of = as_of or date.today()
    visits = [v for v in (confirmed or {}).get("visits") or [] if F.day_of(v)]
    latest = max(visits, key=lambda v: F.day_of(v)) if visits else None
    detail: dict[str, dict] = {}
    for system, names in F.SYSTEM_FIELDS.items():
        has_data = bool(latest) and any(
            latest.get(name) not in (None, "unknown") for name in names)
        notes: list[str] = []
        calculable = False
        if system == "cardiovascular":
            required = ("age", "sbp", "total_c", "hdl_c", "bmi", "egfr", "dm", "smoking",
                        "bp_tx", "statin")
            missing = [F.VISIT_FIELDS[name].label for name in required
                       if latest is None or latest.get(name) is None]
            unknowns = [F.VISIT_FIELDS[name].label for name in required
                        if latest is not None and latest.get(name) is None
                        and is_unknown_field(confirmed, latest.get("record_id"), name)]
            if latest is not None and not missing:
                blockers = eligibility(_as_visit(latest))
                if blockers:
                    notes.append("可点亮，但风险数值受限：" + "；".join(blockers))
                elif (as_of - F.day_of(latest)).days > 365:
                    notes.append("可点亮，但最新完整记录已超过 365 天，按平台资料时效策略需先更新")
                else:
                    calculable = True
            else:
                unknown_note = [name for name in unknowns if name not in missing]
                if missing:
                    notes.append("缺少：" + "、".join(missing))
                if unknown_note:
                    notes.append("已标记不知道：" + "、".join(unknown_note))
        else:
            calculable = has_data
            if not has_data:
                notes.append("缺少：" + "、".join(F.VISIT_FIELDS[name].label for name in names))
            if latest is not None:
                for name in names:
                    if latest.get(name) is None and is_unknown_field(
                            confirmed, latest.get("record_id"), name):
                        notes.append(f"{F.VISIT_FIELDS[name].label}已标记不知道")
        detail[system] = {"has_data": has_data, "calculable": calculable, "notes": notes}
    return detail


def availability(detail: dict[str, dict]) -> dict[str, bool]:
    return {system: bool(item["has_data"]) for system, item in detail.items()}


def capability_lines(detail: dict[str, dict], confirmed: dict | None) -> list[str]:
    if not confirmed or not (confirmed.get("visits") or []):
        return ["当前没有已确认资料；草稿不会点亮人体，也不参与规划。"]
    lines: list[str] = []
    for system, item in detail.items():
        label = F.SYSTEM_LABELS[system]
        if item["calculable"]:
            lines.append(f"{label}：资料已确认，可生成规划建议。")
        elif item["has_data"]:
            note = "；".join(item["notes"]) or "资料不完整"
            lines.append(f"{label}：已有资料，暂不能计算 —— {note}")
        else:
            note = "；".join(item["notes"]) or "尚无该项指标"
            lines.append(f"{label}：尚无已确认资料 —— {note}")
    return lines


# 明确“不知道”时受影响的能力说明：只描述算不了什么，不编造补偿性结论。
UNKNOWN_NOTES = {
    "smoking": "无法计算心血管长期风险（PREVENT 需要当前吸烟状态）",
    "bp_tx": "无法计算心血管长期风险（需要是否使用降压药）",
    "statin": "无法计算心血管长期风险（需要是否使用他汀）",
    "dm": "无法计算心血管长期风险（需要糖尿病病史）",
    "sbp": "无法计算心血管长期风险（缺少收缩压）",
    "total_c": "无法计算心血管长期风险（缺少总胆固醇）",
    "hdl_c": "无法计算心血管长期风险（缺少 HDL 胆固醇）",
    "bmi": "无法计算心血管长期风险（缺少 BMI）",
    "egfr": "无法计算心血管长期风险，也无法给出肾功能随访提醒（缺少 eGFR）",
    "age": "无法计算心血管长期风险（缺少检查时年龄）",
    "sex": "无法计算心血管长期风险（缺少生理性别）",
    "chol_unit": "无法换算或比较胆固醇数值",
    "fasting_glucose": "无法判断血糖与代谢资料是否正常",
    "hba1c": "无法判断血糖与代谢资料是否正常",
}


def unknown_note(name: str | None) -> str | None:
    return UNKNOWN_NOTES.get(name or "")


def _as_visit(visit: dict):
    from app.schemas.prevention import Visit

    return Visit(**F.visit_payload(visit))
