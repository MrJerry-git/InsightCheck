"""白名单动作的服务端校验与执行。

模型提出的动作在这里逐条检查字段、目标范围与确认状态；未通过的动作不写入，
并由服务端给出真实变更摘要。所有写入都在调用方的事务内完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.conversation import ActionLog
from app.schemas.prevention import PreventionRequest
from app.services.conversation import draft as D
from app.services.conversation import fields as F
from app.services.conversation import parser as P
from app.services.conversation.errors import ValidationFailed
from app.services.conversation.model import RawAction
from app.services.conversation.store import (
    Workspace,
    last_undoable,
    mark_snapshots_stale,
    queue_action,
    restore_state,
)

SOURCE_NOTE = "对话式导入，已由用户逐项核对确认"


@dataclass
class Outcome:
    """一次消息处理的实际结果。"""

    summaries: list[dict] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    confirmed_changed: bool = False

    def lines(self) -> list[str]:
        parts = [describe_summary(item) for item in self.summaries]
        parts.extend(item["reason"] for item in self.rejections)
        parts.extend(self.notes)
        return [part for part in parts if part]


def describe_summary(item: dict) -> str:
    spec = F.spec_for(item.get("field") or "")
    label = spec.label if spec else item.get("field")
    unit = f" {item['unit']}" if item.get("unit") else ""
    action = item.get("action")
    if action == "add_visit":
        return f"已加入待核对记录：{item.get('date') or '未标明日期'}。"
    if action == "confirm":
        return f"已确认 {item.get('visits')} 条检查记录并写入历史档案。"
    if action == "update_visit":
        scope = "已确认资料" if item.get("scope") == "confirmed" else "草稿"
        converted = "，已按登记换算一次" if item.get("converted") else ""
        return f"已更新{scope}：{label} = {item.get('value')}{unit}{converted}。"
    if action == "update_profile":
        return f"已更新{label} = {item.get('value')}。"
    if action == "delete_visit":
        return f"已删除记录 {item.get('date') or item.get('record_id')}，可在撤销窗口内恢复。"
    if action == "undo":
        return "已撤销最近一次修改。"
    if action == "cancel":
        return "已取消待执行动作，资料没有变化。"
    if action == "unknown_explicit":
        return f"已把{label}记为“不知道”，该字段保持未知，不会当成“否”。"
    return item.get("reason") or ""


def record_label(visit: dict) -> str:
    day = F.day_text(visit) or "未标明日期"
    detail = []
    for name in ("fasting_glucose", "hba1c", "sbp", "egfr"):
        if visit.get(name) is not None:
            spec = F.VISIT_FIELDS[name]
            detail.append(f"{spec.label} {visit[name]}{spec.unit or ''}")
    tail = "、".join(detail) if detail else "记录"
    return f"{day}（{tail}，编号 {visit.get('record_id')}）"


def scoped(ws: Workspace) -> list[tuple[str, dict, dict]]:
    """(scope, container, visit)；已确认资料在前。"""
    entries: list[tuple[str, dict, dict]] = []
    confirmed = ws.confirmed()
    for visit in (confirmed or {}).get("visits") or []:
        entries.append(("confirmed", confirmed, visit))
    draft = ws.draft_data()
    for visit in draft.get("visits") or []:
        entries.append(("draft", draft, visit))
    return entries


def locate(ws: Workspace, *, record_id: str | None = None, day: date | None = None,
           year: int | None = None, month: int | None = None) -> list[tuple[str, dict, dict]]:
    matches = []
    for scope, container, visit in scoped(ws):
        current = F.day_of(visit)
        if record_id:
            if visit.get("record_id") == record_id:
                matches.append((scope, container, visit))
            continue
        if day is not None:
            if current == day:
                matches.append((scope, container, visit))
            continue
        if year is None and month is None or current is None:
            continue
        if year is not None and current.year != year:
            continue
        if month is not None and current.month != month:
            continue
        matches.append((scope, container, visit))
    return matches


def mutate_confirmed(ws: Workspace, outcome: Outcome, **changes) -> dict:
    confirmed = dict(ws.confirmed() or {})
    confirmed.update(changes)
    ws.profile.confirmed = confirmed
    outcome.confirmed_changed = True
    return confirmed


def apply_action(db: Session, ws: Workspace, action: RawAction, outcome: Outcome, *,
                 today: date | None = None) -> None:
    today = today or date.today()
    handlers = {"add_visit": _add_visit, "update_visit": _update_visit,
                "update_profile": _update_profile, "delete_visit": _delete_visit,
                "undo": _undo}
    handlers[action.type](db, ws, action, outcome, today=today)


def resolve_action(db: Session, ws: Workspace, action: RawAction, outcome: Outcome,
                   *, answer: str = "", today: date | None = None) -> None:
    """重新执行被追问过的动作，并把用户补充的说明并入解析文本。"""
    merged = dict(action.model_dump())
    if answer:
        base = merged.get("value_text") or ""
        merged["value_text"] = (base + " " + answer).strip()
    if merged.get("unit_intent") == "unknown":
        merged["unit_intent"] = None
    apply_action(db, ws, RawAction(**merged), outcome, today=today)


def _parse_visit_fields(payload: dict, outcome: Outcome) -> dict:
    parsed: dict = {}
    for name, text in payload.items():
        spec = F.spec_for(name)
        if spec is None or name not in F.VISIT_FIELDS:
            outcome.rejections.append({"field": name,
                                       "reason": f"忽略了未登记的字段：{name}。"})
            continue
        value = P.parse_value_text(name, text, None).value
        if value is None:
            if name in F.VISIT_REQUIRED:
                outcome.rejections.append({
                    "field": name,
                    "reason": f"{spec.label}的内容无法解析，已留空等待确认。"})
            continue
        ok, reason = F.validate_field_value(name, value)
        if not ok:
            outcome.rejections.append({"field": name, "reason": reason + "，已忽略该值。"})
            continue
        parsed[name] = value.isoformat() if isinstance(value, date) else value
    return parsed


def _add_visit(db: Session, ws: Workspace, action: RawAction, outcome: Outcome, *,
               today: date) -> None:
    payload = dict(action.fields or {})
    if action.field and action.value_text is not None:
        payload[action.field] = action.value_text
    if action.date:
        payload["date"] = action.date
    day = P.parse_date(str(payload.get("date") or ""), today)
    if "date" in payload and day is None:
        outcome.rejections.append({
            "field": "date",
            "reason": f"日期“{payload.get('date')}”无法识别，请用 YYYY-MM-DD 或“去年 5 月”"
                      "这样的写法，原记录保持不变。"})
    values = _parse_visit_fields({key: value for key, value in payload.items()
                                  if key != "date"}, outcome)
    duplicates = locate(ws, day=day) if day else []
    if duplicates:
        scope, _, visit = duplicates[0]
        _queue_duplicate(db, ws, visit, values, scope, day, outcome)
        return
    draft = ws.draft_data()
    if day is None:
        undated = [visit for visit in draft["visits"] if visit.get("date") is None]
        if undated:
            undated[-1].update(values)
            ws.set_draft(draft)
            outcome.summaries.append({"action": "add_visit",
                                      "record_id": undated[-1]["record_id"], "date": None,
                                      "fields": sorted(values)})
            return
    visit = D.new_visit(day)
    visit.update(values)
    draft["visits"].append(visit)
    for name, text in payload.items():
        if name == "date" or name in values or name not in F.VISIT_FIELDS:
            continue
        if P.is_unknown(str(text)):
            D.set_unknown(draft, visit["record_id"], name)
    ws.set_draft(draft)
    outcome.summaries.append({"action": "add_visit", "record_id": visit["record_id"],
                              "date": day.isoformat() if day else None,
                              "fields": sorted(values)})


def _queue_duplicate(db: Session, ws: Workspace, visit: dict, values: dict, scope: str,
                     day: date, outcome: Outcome) -> None:
    question = (f"{day.isoformat()} 已经有一条记录（编号 {visit.get('record_id')}）。"
                "请选择：覆盖该记录 / 保留原记录 / 放弃新资料。")
    queue_action(db, ws, "duplicate_date", {
        "action": "duplicate_date", "question": question, "day": day.isoformat(),
        "record_id": visit.get("record_id"), "scope": scope, "values": values})
    outcome.pending.append(question)
    outcome.notes.append("同日重复资料没有自动新增或覆盖，等待用户选择处理方式。")


def _update_visit(db: Session, ws: Workspace, action: RawAction, outcome: Outcome, *,
                  today: date) -> None:
    name = action.field or ""
    if not name or name not in F.VISIT_FIELDS:
        outcome.rejections.append({"field": name,
                                   "reason": f"“{name}”不是可直接修改的记录字段，已忽略。"})
        return
    matches = _matches_for_update(ws, action, today)
    if not matches:
        outcome.rejections.append({
            "field": "record_id",
            "reason": "没有找到要修改的记录，请说明年份或日期，原记录保持不变。"})
        return
    if len(matches) > 1:
        _ask_choose_record(db, ws, action, matches, "修改", outcome)
        return
    scope, container, visit = matches[0]
    if P.is_unknown(action.value_text or ""):
        _mark_unknown(ws, scope, container, visit, name, outcome)
        return
    intent = action.unit_intent or "unknown"
    if name == "chol_unit":
        if intent == "label":
            _change_cholesterol_unit(db, ws, action, outcome, today=today, convert=False)
        elif intent == "value":
            _change_cholesterol_unit(db, ws, action, outcome, today=today, convert=True)
        else:
            ask_unit_intent(db, ws, action, "chol_unit", visit, "", F.unit_of(name, visit),
                             outcome)
        return
    if intent == "label" and name not in F.CHOLESTEROL_FIELDS:
        outcome.rejections.append({
            "field": name,
            "reason": f"{F.VISIT_FIELDS[name].label}固定使用登记单位，"
                      "请说明是否要按登记换算数值。"})
        return
    if intent == "label":
        _change_cholesterol_unit(db, ws, action, outcome, today=today, convert=False)
        return
    unit = action.unit or P.parse_unit(action.value_text or "")
    current_unit = F.unit_of(name, visit)
    if (unit and name in F.ALLOWED_UNITS and intent == "unknown" and current_unit is not None
            and unit != current_unit and visit.get(name) is not None):
        ask_unit_intent(db, ws, action, name, visit, unit, current_unit, outcome)
        return
    parsed = P.parse_value_text(name, action.value_text, unit, today)
    if parsed.value is None:
        outcome.rejections.append({
            "field": name,
            "reason": f"{F.VISIT_FIELDS[name].label}的内容无法解析，原记录保持不变。"})
        return
    value = parsed.value
    converted = False
    basis = None
    unit_patch: str | None = None
    if name in F.ALLOWED_UNITS and parsed.unit:
        resolved = _resolve_unit(visit, name, float(value), parsed.unit, intent)
        if resolved is None:
            ask_unit_intent(db, ws, action, name, visit, parsed.unit, current_unit, outcome)
            return
        value, converted, basis, unit_patch = resolved
    ok, reason = F.validate_field_value(name, value, visit)
    if not ok:
        outcome.rejections.append({"field": name, "reason": reason + "，原记录保持不变。"})
        return
    conflict = _cholesterol_conflict(name, value, visit)
    if conflict:
        outcome.rejections.append({"field": name, "reason": conflict})
        return
    apply_to = dict(visit)
    apply_to[name] = value
    if unit_patch:
        apply_to["chol_unit"] = unit_patch
    if not _store_visit(ws, outcome, scope, container, visit, apply_to):
        return
    summary = {"action": "update_visit", "record_id": visit.get("record_id"), "field": name,
               "value": value, "unit": F.unit_of(name, apply_to), "scope": scope,
               "converted": converted}
    if basis:
        summary["basis"] = basis
    outcome.summaries.append(summary)


def _cholesterol_conflict(name: str, value: float, visit: dict) -> str | None:
    if name not in F.CHOLESTEROL_FIELDS:
        return None
    other = "hdl_c" if name == "total_c" else "total_c"
    counterpart = visit.get(other)
    if counterpart is None:
        return None
    if name == "hdl_c" and value >= counterpart:
        return "HDL 胆固醇必须小于总胆固醇，请确认单位与数值，原记录保持不变。"
    if name == "total_c" and counterpart >= value:
        return "总胆固醇必须大于 HDL 胆固醇，请确认单位与数值，原记录保持不变。"
    return None


def _matches_for_update(ws: Workspace, action: RawAction,
                        today: date) -> list[tuple[str, dict, dict]]:
    text = target_text(action)
    day = P.parse_date(text, today) if text else None
    period = P.parse_period(text, today) if text else None
    matches = locate(ws, record_id=action.record_id, day=day)
    if not matches and period and day is None:
        matches = locate(ws, year=period.year, month=period.month)
    if not matches and not action.record_id and not action.date:
        matches = scoped(ws)
    return matches


def target_text(action: RawAction) -> str:
    """定位记录用的文本：动作里的日期与用户原话都参与解析。"""
    return " ".join(part for part in (action.date, action.value_text) if part)


def _resolve_unit(visit: dict, name: str, value: float, unit: str, intent: str
                  ) -> tuple[float, bool, str | None, str | None] | None:
    """返回 (数值, 是否换算, 依据, 需要同时写入的单位标签)。"""
    current_unit = F.unit_of(name, visit)
    if name in F.CHOLESTEROL_FIELDS and visit.get("chol_unit") is None:
        return value, False, None, unit
    if current_unit is None or unit == current_unit:
        return value, False, None, None
    if intent == "label":
        return None
    converted = F.convert_value(name, value, unit, current_unit)
    if converted is None:
        return None
    return converted[0], True, converted[1], None


def _change_cholesterol_unit(db: Session, ws: Workspace, action: RawAction, outcome: Outcome,
                             *, today: date, convert: bool) -> None:
    """胆固醇单位：convert=False 只纠正标签，convert=True 按登记换算数值一次。"""
    matches = _matches_for_update(ws, action, today)
    if not matches:
        outcome.rejections.append({"field": "chol_unit",
                                   "reason": "没有找到要纠正单位的记录，原记录保持不变。"})
        return
    if len(matches) > 1:
        _ask_choose_record(db, ws, action, matches, "纠正单位", outcome)
        return
    scope, container, visit = matches[0]
    unit = action.unit or P.parse_unit(action.value_text or "")
    if unit not in ("mmol/L", "mg/dL"):
        ask_unit_intent(db, ws, action, "chol_unit", visit, unit or "", None, outcome)
        return
    current = visit.get("chol_unit")
    if current is None:
        # 单位原本未知：这次只登记单位，并做数值一致性检查，不做换算。
        convert = False
    elif current == unit:
        outcome.notes.append(f"这条记录的单位已经是 {unit}，没有改动。")
        return
    if convert:
        converted_fields: dict[str, float] = {}
        basis = None
        for name in F.CHOLESTEROL_FIELDS:
            value = visit.get(name)
            if value is None:
                continue
            result = F.convert_value(name, float(value), current, unit)
            if result is None:
                outcome.rejections.append({
                    "field": name,
                    "reason": f"{F.VISIT_FIELDS[name].label}没有登记从 {current} 到 {unit} "
                              "的换算，原记录保持不变。"})
                return
            converted_fields[name], basis = result
        apply_to = dict(visit)
        apply_to.update(converted_fields)
        apply_to["chol_unit"] = unit
        if not _store_visit(ws, outcome, scope, container, visit, apply_to):
            return
        outcome.summaries.append({"action": "update_visit",
                                  "record_id": visit.get("record_id"), "field": "chol_unit",
                                  "value": unit, "unit": unit, "scope": scope,
                                  "converted": True, "basis": basis,
                                  "converted_fields": converted_fields})
        return
    blocking = []
    for name in F.CHOLESTEROL_FIELDS:
        value = visit.get(name)
        if value is not None and not F.plausible(name, value, unit):
            low, high = F.PLAUSIBLE_RANGES[(name, unit)]
            blocking.append(f"{F.VISIT_FIELDS[name].label} {value} 在 {unit} 下不在 "
                            f"{low:g}–{high:g} 的合理范围")
    if blocking:
        outcome.rejections.append({
            "field": "chol_unit",
            "reason": "改成该单位后数值不一致：" + "；".join(blocking)
                      + "。请说明是单位写错还是要换算数值，原记录保持不变。"})
        return
    apply_to = dict(visit)
    apply_to["chol_unit"] = unit
    if not _store_visit(ws, outcome, scope, container, visit, apply_to):
        return
    outcome.summaries.append({"action": "update_visit", "record_id": visit.get("record_id"),
                              "field": "chol_unit", "value": unit, "unit": unit,
                              "scope": scope, "converted": False})


def _store_visit(ws: Workspace, outcome: Outcome, scope: str, container: dict, original: dict,
                 updated: dict) -> bool:
    """写入一条记录；已确认资料必须先通过一致性校验，返回是否真的写入了。"""
    if scope == "confirmed":
        visits = [updated if visit is original else visit
                  for visit in container.get("visits") or []]
        if not _confirmed_candidate_ok(ws, visits, outcome):
            return False
        mutate_confirmed(ws, outcome, visits=visits)
        return True
    draft = ws.draft_data()
    for visit in draft["visits"]:
        if visit.get("record_id") == original.get("record_id"):
            visit.update({key: value for key, value in updated.items()})
    ws.set_draft(draft)
    return True


def _confirmed_candidate_ok(ws: Workspace, visits: list[dict], outcome: Outcome) -> bool:
    """已确认资料的任何改动都要先通过服务端一致性校验，否则保留原记录。"""
    candidate = dict(ws.confirmed() or {})
    candidate["visits"] = [F.normalize_visit(visit) for visit in visits]
    try:
        validate_merged(candidate, label=ws.profile.display_name, today=date.today())
    except ValidationFailed as exc:
        reasons = "；".join(error["msg"] for error in exc.errors)
        outcome.rejections.append({
            "field": None,
            "reason": f"这次修改会让已确认资料不一致（{reasons}），原记录保持不变。"})
        return False
    return True


def _ask_choose_record(db: Session, ws: Workspace, action: RawAction,
                       matches: list[tuple[str, dict, dict]], purpose: str,
                       outcome: Outcome) -> None:
    options = "；".join(record_label(visit) for _, _, visit in matches)
    question = f"要{purpose}哪一条记录？请说明日期或编号：" + options
    queue_action(db, ws, "choose_record", {
        "action": "choose_record", "question": question, "purpose": purpose,
        "original": action.model_dump(),
        "candidates": [{"record_id": visit.get("record_id"), "scope": scope,
                        "date": F.day_text(visit)}
                       for scope, _, visit in matches]})
    outcome.pending.append(question)
    outcome.notes.append("目标不唯一，没有默认选择“最新一条”。")


def ask_choose_field(db: Session, ws: Workspace, candidates: tuple[str, ...], question: str,
                     outcome: Outcome, original: dict | None = None) -> None:
    labels = "、".join(F.VISIT_FIELDS[name].label for name in candidates)
    pending = f"{question}可选指标：{labels}。"
    queue_action(db, ws, "choose_field", {"action": "choose_field", "question": pending,
                                          "candidates": list(candidates),
                                          "original": original or {}})
    outcome.pending.append(pending)


def ask_unit_intent(db: Session, ws: Workspace, action: RawAction, name: str, visit: dict,
                     unit: str, current_unit: str | None, outcome: Outcome) -> None:
    if name == "chol_unit" and not unit:
        question = "请说明胆固醇单位是 mmol/L 还是 mg/dL，以及是改标签还是换算数值。"
    else:
        label = F.VISIT_FIELDS[name].label
        question = (f"{label}的单位从 {current_unit or '未标注'} 变成 {unit or '未标注'}："
                    "是单位标签写错了（数值不变），还是要按登记换算数值？")
    queue_action(db, ws, "choose_unit", {
        "action": "choose_unit", "question": question, "field": name,
        "record_id": visit.get("record_id"), "unit": unit, "current_unit": current_unit,
        "original": action.model_dump()})
    outcome.pending.append(question)


def _mark_unknown(ws: Workspace, scope: str, container: dict, visit: dict, name: str,
                  outcome: Outcome) -> None:
    """明确“不知道”：保持未知（清空该字段）并记录受限字段，不补默认值。"""
    if scope == "draft":
        draft = ws.draft_data()
        for item in draft["visits"]:
            if item.get("record_id") == visit.get("record_id"):
                item[name] = None
        D.set_unknown(draft, visit.get("record_id"), name)
        ws.set_draft(draft)
    else:
        visits = [{**item, name: None} if item is visit else item
                  for item in container.get("visits") or []]
        unknowns = list(container.get("unknowns") or [])
        target = D.path(visit.get("record_id") or "", name)
        if target not in unknowns:
            unknowns.append(target)
        mutate_confirmed(ws, outcome, visits=visits, unknowns=unknowns)
    outcome.summaries.append({"action": "unknown_explicit", "field": name,
                              "record_id": visit.get("record_id"), "scope": scope})


def _update_profile(db: Session, ws: Workspace, action: RawAction, outcome: Outcome, *,
                    today: date) -> None:
    name = action.field or ""
    if name not in F.PROFILE_FIELDS:
        outcome.rejections.append({"field": name,
                                   "reason": f"“{name}”不是可修改的档案字段，已忽略。"})
        return
    parsed = P.parse_value_text(name, action.value_text)
    confirmed = ws.confirmed()
    if parsed.unknown:
        if confirmed and confirmed.get("visits"):
            unknowns = list(confirmed.get("unknowns") or [])
            if name not in unknowns:
                unknowns.append(name)
            mutate_confirmed(ws, outcome, unknowns=unknowns, **{name: None})
        else:
            draft = ws.draft_data()
            draft[name] = None
            D.set_unknown(draft, None, name)
            ws.set_draft(draft)
        outcome.summaries.append({"action": "unknown_explicit", "field": name})
        return
    if parsed.value is None:
        outcome.rejections.append({"field": name,
                                   "reason": f"{F.PROFILE_FIELDS[name].label}的内容无法解析，"
                                             "已保留原值。"})
        return
    ok, reason = F.validate_field_value(name, parsed.value)
    if not ok:
        outcome.rejections.append({"field": name, "reason": reason + "，已保留原值。"})
        return
    if confirmed and confirmed.get("visits"):
        mutate_confirmed(ws, outcome, **{name: parsed.value})
    else:
        draft = ws.draft_data()
        draft[name] = parsed.value
        D.clear_unknown(draft, None, name)
        ws.set_draft(draft)
    outcome.summaries.append({"action": "update_profile", "field": name,
                              "value": parsed.value})


def _delete_visit(db: Session, ws: Workspace, action: RawAction, outcome: Outcome, *,
                  today: date) -> None:
    text = target_text(action)
    day = P.parse_date(text, today) if text else None
    period = P.parse_period(text, today) if text else None
    matches = locate(ws, record_id=action.record_id, day=day)
    if not matches and period and day is None:
        matches = locate(ws, year=period.year, month=period.month)
    if not matches:
        outcome.rejections.append({
            "field": "record_id",
            "reason": "没有找到要删除的记录，请说明年份或日期，资料保持不变。"})
        return
    if len(matches) > 1:
        _ask_choose_record(db, ws, action, matches, "删除", outcome)
        return
    scope, _, visit = matches[0]
    if len(scoped(ws)) <= 1:
        outcome.rejections.append({
            "field": "record_id",
            "reason": "删除后档案将没有任何检查记录，请先补充新记录再删除这一条。"})
        return
    question = (f"确认删除这条记录吗？{record_label(visit)}。"
                "确认后才执行，删除后仍可撤销。")
    queue_action(db, ws, "delete_confirm", {
        "action": "delete_visit", "question": question,
        "record_id": visit.get("record_id"), "scope": scope,
        "date": F.day_text(visit),
        "original": action.model_dump()})
    outcome.pending.append(question)
    outcome.notes.append("删除先确认目标，确认前没有删除任何资料。")


def execute_delete(db: Session, ws: Workspace, record_id: str, outcome: Outcome) -> None:
    matches = locate(ws, record_id=record_id)
    if not matches:
        outcome.rejections.append({"field": "record_id",
                                   "reason": "要删除的记录已不存在，资料保持不变。"})
        return
    scope, container, visit = matches[0]
    if len(scoped(ws)) <= 1:
        outcome.rejections.append({"field": "record_id",
                                   "reason": "删除后档案将没有任何检查记录，已取消该操作。"})
        return
    if scope == "confirmed":
        visits = [item for item in container.get("visits") or [] if item is not visit]
        deleted = list(container.get("deleted") or [])
        deleted.append({**visit, "deleted_at": date.today().isoformat()})
        mutate_confirmed(ws, outcome, visits=visits, deleted=deleted)
    else:
        draft = ws.draft_data()
        draft["visits"] = [item for item in draft["visits"]
                           if item.get("record_id") != record_id]
        ws.set_draft(draft)
    outcome.summaries.append({"action": "delete_visit", "record_id": record_id,
                              "scope": scope, "soft": True,
                              "date": F.day_text(visit)})


def apply_values_to_record(db: Session, ws: Workspace, record_id: str | None, values: dict,
                           outcome: Outcome) -> None:
    """把（用户选择“覆盖”）的新数值写入指定记录。"""
    matches = locate(ws, record_id=record_id) if record_id else []
    if not matches:
        outcome.rejections.append({"field": "record_id",
                                   "reason": "要覆盖的记录已不存在，资料保持不变。"})
        return
    scope, container, visit = matches[0]
    apply_to = dict(visit)
    for name, value in values.items():
        if name in F.VISIT_FIELDS and value is not None:
            apply_to[name] = value
    if not _store_visit(ws, outcome, scope, container, visit, apply_to):
        return
    outcome.summaries.append({"action": "update_visit", "record_id": record_id,
                              "field": "visit", "scope": scope,
                              "value": F.day_text(apply_to),
                              "fields": sorted(name for name in values
                                               if name in F.VISIT_FIELDS)})


def _undo(db: Session, ws: Workspace, action: RawAction, outcome: Outcome, *,
          today: date) -> None:
    log = last_undoable(db, ws.profile_id)
    if log is None or not log.before:
        outcome.rejections.append({
            "field": None,
            "reason": "没有可撤销的修改；撤销只覆盖最近一次成功的数据修改或删除。"})
        return
    current_version = ws.profile.version
    confirmed_before = ws.profile.confirmed
    restore_state(ws.profile, ws.draft_row, log.before)
    if log.before.get("confirmed") != confirmed_before:
        # 撤销也是一次真实的档案变更：版本继续前进，旧规划保持过期状态。
        ws.profile.version = max(current_version, int(log.before.get("version") or 0)) + 1
        mark_snapshots_stale(db, ws.profile_id)
        ws.profile.analysis_stale = True
    log.undone = True
    # 只允许撤销最近一次修改：撤销后清空撤销上下文，避免把撤销链继续往回套。
    db.execute(update(ActionLog)
               .where(ActionLog.profile_id == ws.profile_id,
                      ActionLog.undoable.is_(True))
               .values(undone=True))
    outcome.summaries.append({"action": "undo", "undone_log": log.id})
    outcome.notes.append("已恢复到该次修改之前的档案状态。")


# ------------------------------------------------------------- 草稿合并、校验与确认


def unknown_blockers(merged: dict) -> list[str]:
    """被明确标记“不知道”的必填项：不能补默认值，也不能进入评估。"""
    blockers: list[str] = []
    visits = {visit.get("record_id"): visit for visit in merged.get("visits") or []}
    for target in merged.get("unknowns") or []:
        if target.startswith("visits."):
            parts = target.split(".", 2)
            if len(parts) != 3:
                continue
            _, record_id, name = parts
            visit = visits.get(record_id)
            if visit is None or name not in D.required_visit_fields(visit):
                continue
            blockers.append(f"{F.day_text(visit) or '待补日期'} 的 "
                            f"{F.VISIT_FIELDS[name].label}")
        elif target in F.PROFILE_REQUIRED:
            blockers.append(F.PROFILE_FIELDS[target].label)
    return blockers


def merge_confirmed(ws: Workspace) -> dict:
    """把草稿合并进已确认资料：新增记录追加，不覆盖已有的其他年份记录。"""
    draft = ws.draft_data()
    confirmed = dict(ws.confirmed() or {})
    visits = [dict(visit) for visit in confirmed.get("visits") or []]
    existing = {visit.get("record_id"): visit for visit in visits}
    for visit in draft.get("visits") or []:
        if visit.get("record_id") in existing:
            existing[visit["record_id"]].update(visit)
        elif visit.get("date") is not None or any(visit.get(name) is not None
                                                 for name in F.VISIT_REQUIRED):
            visits.append(dict(visit))
    merged = {**confirmed, "visits": visits}
    for name in F.PROFILE_FIELDS:
        if draft.get(name) is not None:
            merged[name] = draft[name]
    merged["unknowns"] = list(dict.fromkeys([*(confirmed.get("unknowns") or []),
                                             *(draft.get("unknowns") or [])]))
    return merged


def build_request(merged: dict, *, label: str, today: date) -> PreventionRequest:
    visits = [F.visit_payload(visit) for visit in merged.get("visits") or []
              if visit.get("date") is not None]
    return PreventionRequest(
        label=(label or "体检档案")[:80], sex=merged.get("sex"),
        known_cvd=merged.get("known_cvd"), pregnant=merged.get("pregnant"),
        symptomatic=merged.get("symptomatic"), source="manual", source_note=SOURCE_NOTE,
        as_of=today, visits=visits)


def validate_merged(merged: dict, *, label: str, today: date) -> dict:
    """服务端确定性校验；失败抛 ValidationFailed，草稿保持原样。"""
    if not merged.get("visits"):
        raise ValidationFailed("还没有可确认的检查记录。", errors=[
            {"loc": ["visits"], "msg": "至少需要一条检查记录"}], missing=["visits"])
    unknown_required = unknown_blockers(merged)
    if unknown_required:
        raise ValidationFailed(
            "以下必填项被标记为“不知道”，无法用默认值代替：" + "、".join(unknown_required),
            errors=[{"loc": [item], "msg": "用户已确认该字段未知，不能补默认值"}
                    for item in unknown_required],
            missing=D.missing_paths(merged, include_unknown=True))
    try:
        request = build_request(merged, label=label, today=today)
    except ValidationError as exc:
        errors = [{"loc": [str(part) for part in error["loc"]], "msg": error["msg"]}
                  for error in exc.errors()]
        raise ValidationFailed("资料未通过校验，草稿已保留。", errors=errors,
                               missing=D.missing_paths(merged)) from None
    payload = request.model_dump(mode="json")
    confirmed = {key: payload[key] for key in
                 ("sex", "known_cvd", "pregnant", "symptomatic", "as_of", "source",
                  "source_note", "label")}
    confirmed["visits"] = sorted(
        (F.normalize_visit(visit) for visit in merged.get("visits") or []),
        key=lambda visit: visit.get("date") or "")
    confirmed["unknowns"] = list(merged.get("unknowns") or [])
    confirmed["deleted"] = list(merged.get("deleted") or [])
    return confirmed


def confirm_draft(db: Session, ws: Workspace, outcome: Outcome, *,
                  today: date | None = None) -> dict:
    today = today or date.today()
    merged = merge_confirmed(ws)
    confirmed = validate_merged(merged, label=ws.profile.display_name, today=today)
    ws.profile.confirmed = confirmed
    outcome.confirmed_changed = True
    outcome.summaries.append({"action": "confirm", "visits": len(confirmed["visits"])})
    return confirmed


def apply_extraction(db: Session, ws: Workspace, extracted: dict, outcome: Outcome, *,
                     today: date | None = None) -> None:
    """把 smart-import 提取结果合并进草稿；只写草稿，确认前不点亮人体。"""
    today = today or date.today()
    draft = ws.draft_data()
    applied = 0
    for name in F.PROFILE_FIELDS:
        value = extracted.get(name)
        if value is None:
            continue
        ok, reason = F.validate_field_value(name, value)
        if not ok:
            outcome.rejections.append({"field": name, "reason": reason + "，已忽略该值。"})
            continue
        if draft.get(name) is None:
            draft[name] = value
    extracted_visits = extracted.get("visits") or []
    if not extracted_visits:
        outcome.notes.append("本次资料没有识别出检查记录，草稿保持不变。")
    for raw in extracted_visits:
        values = {}
        for name in F.VISIT_FIELDS:
            value = raw.get(name)
            if value is None or (name == "glucose_status" and value == "unknown"):
                continue
            if name == "date" and not isinstance(value, date):
                value = P.parse_date(str(value), today)
                if value is None:
                    outcome.rejections.append({
                        "field": "date",
                        "reason": f"日期“{raw.get('date')}”无法识别，请补充后重试。"})
                    continue
            ok, reason = F.validate_field_value(name, value, raw)
            if not ok:
                outcome.rejections.append({"field": name, "reason": reason + "，已忽略该值。"})
                continue
            values[name] = value.isoformat() if isinstance(value, date) else value
        day = F.day_of(values)
        duplicates = locate(ws, day=day) if day else []
        if duplicates:
            scope, _, visit = duplicates[0]
            _queue_duplicate(db, ws, visit, values, scope, day, outcome)
            continue
        if not values:
            continue
        visit = D.new_visit(day)
        visit.update(values)
        draft["visits"].append(visit)
        applied += 1
        outcome.summaries.append({"action": "add_visit", "record_id": visit["record_id"],
                                  "date": day.isoformat() if day else None,
                                  "fields": sorted(values)})
    for warning in extracted.get("warnings") or []:
        draft.setdefault("warnings", []).append(str(warning)[:500])
    ws.set_draft(draft)
    if not applied and not outcome.rejections and not outcome.pending:
        outcome.notes.append("这次没有识别出可核对的字段，请检查原文，或直接补充缺少的信息。")
