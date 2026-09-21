"""对话编排：把一轮消息转换为确定性解析或模型提案，并只提交真实结果。

所有写操作都携带 op_id（幂等键）与可选 expected_version；每次处理是单事务：
动作全部通过校验才提交，异常时回滚，绝不产生半完成写入。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.conversation import ActionLog, ArchiveSnapshot, Profile
from app.schemas.conversation import NewProfileRequest
from app.schemas.smart_import import ImportRequest
from app.services.conversation import draft as D
from app.services.conversation import executor as X
from app.services.conversation import fields as F
from app.services.conversation import model as M
from app.services.conversation import parser as P
from app.services.conversation import plans as PL
from app.services.conversation import store as S
from app.services.conversation.errors import (
    ConversationError,
    InvalidInput,
    ProfileNotFound,
    VersionConflict,
)
from app.services.conversation.model import RawAction

UNDOABLE_ACTIONS = {"add_visit", "update_visit", "update_profile", "delete_visit",
                    "unknown_explicit"}


def service_state() -> str:
    return "ready"


# ------------------------------------------------------------------ 状态序列化


def system_history(confirmed: dict | None) -> dict:
    visits = sorted((confirmed or {}).get("visits") or [], key=lambda v: v.get("date") or "")
    history: dict[str, dict] = {}
    for system, names in F.SYSTEM_FIELDS.items():
        points: dict[str, list] = {name: [] for name in names}
        for visit in visits:
            for name in names:
                value = visit.get(name)
                if value in (None, "unknown"):
                    continue
                points[name].append({"date": F.day_text(visit), "value": value,
                                     "record_id": visit.get("record_id")})
        history[system] = {"label": F.SYSTEM_LABELS[system], "points": points}
    return history


def profile_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Profile)) or 0


def state_payload(db: Session, ws: S.Workspace, *, today: date | None = None) -> dict:
    today = today or date.today()
    draft = ws.draft_data() if ws.draft_row.data else None
    detail = D.system_detail(ws.profile.confirmed, today)
    snapshot = S.current_snapshot(db, ws.profile_id)
    return {
        "profile_id": ws.profile_id,
        "display_name": ws.profile.display_name,
        "session_id": ws.session_id,
        "version": ws.profile.version,
        "draft_version": ws.draft_row.version,
        "confirmed_data": ws.profile.confirmed,
        "draft": draft,
        "messages": [S.message_summary(row)
                     for row in S.recent_messages(db, ws.profile_id, ws.session_id)],
        "pending_actions": S.pending_payload(db, ws.profile_id),
        "missing": list(ws.draft_row.missing or []),
        "questions": [item.get("question") for item in (ws.draft_row.questions or [])],
        "unknowns": list(dict.fromkeys([
            *(D.unknown_paths(draft) if draft else []),
            *((ws.profile.confirmed or {}).get("unknowns") or [])])),
        "capabilities": list(ws.draft_row.capabilities or []),
        "system_availability": D.availability(detail),
        "system_status": detail,
        "system_history": system_history(ws.profile.confirmed),
        "analysis_stale": bool(ws.profile.analysis_stale),
        "current_snapshot": S.snapshot_summary(snapshot) if snapshot else None,
        "profile_count": profile_count(db),
        "service_state": service_state(),
    }


def refresh_meta(ws: S.Workspace, today: date) -> dict:
    data = ws.draft_row.data
    detail = D.system_detail(ws.profile.confirmed, today)
    ws.draft_row.missing = D.missing_paths(data) if data else []
    ws.draft_row.questions = D.questions_for(data) if data else []
    ws.draft_row.capabilities = D.capability_lines(detail, ws.profile.confirmed)
    return detail


def compose_reply(outcome: X.Outcome, detail: dict, *, confirmed: dict | None,
                  questions: list) -> str:
    parts = outcome.lines()
    unknowns = [item.get("field") for item in outcome.summaries
                if item.get("action") == "unknown_explicit"]
    if unknowns:
        notes = [note for note in (D.unknown_note(name) for name in unknowns) if note]
        if notes:
            parts.append("受限能力：" + "；".join(dict.fromkeys(notes)) + "。")
        if confirmed:
            parts.extend(D.capability_lines(detail, confirmed))
    if questions:
        parts.append("还需要补充：" + "；".join(item["question"] for item in questions[:4]))
    if not parts:
        parts.append("已记录你的说明。")
    return "".join(parts)[:2000]


def _guard_version(ws: S.Workspace, expected: int | None) -> None:
    if expected is not None and expected != ws.profile.version:
        raise VersionConflict("档案已在其他页面被更新，请重新核对后再提交。",
                              details={"current_version": ws.profile.version,
                                       "expected_version": expected})


def _replay(db: Session, profile_id: str, op_id: str) -> dict | None:
    log = S.find_log(db, profile_id, op_id)
    return dict(log.result) if log and log.result else None


def _log(db: Session, profile_id: str, op_id: str, kind: str, request: dict, result: dict,
         before: dict, undoable: bool) -> ActionLog:
    """幂等键为 (profile_id, op_id)；新建档案记在来源档案上，便于重复请求识别。"""
    row = ActionLog(profile_id=profile_id, op_id=op_id, kind=kind, request=request,
                    result=result, before=before, undoable=undoable, undone=False,
                    created_at=S.now())
    db.add(row)
    db.flush()
    return row


def _bump(ws: S.Workspace, db: Session, outcome: X.Outcome) -> None:
    if not outcome.confirmed_changed:
        return
    ws.profile.version = (ws.profile.version or 0) + 1
    if S.current_snapshot(db, ws.profile_id) is None:
        # 还没有任何规划快照时不存在“过期分析”，不虚报过期状态。
        outcome.confirmed_changed = False
        return
    S.mark_snapshots_stale(db, ws.profile_id)
    ws.profile.analysis_stale = True
    outcome.confirmed_changed = False


# ------------------------------------------------------------------ 消息处理


def handle_message(db: Session, profile_id: str, body, *, today: date | None = None
                   ) -> tuple[int, dict]:
    today = today or date.today()
    ws = S.load_workspace(db, profile_id)
    replay = _replay(db, profile_id, body.op_id)
    if replay is not None:
        return 200, replay
    _guard_version(ws, body.expected_version)
    before = S.snapshot_state(ws.profile, ws.draft_row)
    outcome = X.Outcome()
    try:
        if body.file is not None:
            extraction = M.extract_document(ImportRequest(text="", file=body.file))
            X.apply_extraction(db, ws, extraction["draft"], outcome, today=today)
            if body.text.strip():
                outcome.notes.append(
                    "附件内容只作为资料处理；需要执行修改或删除时，请直接说明。")
        else:
            interpret(db, ws, body.text.strip(), outcome, today=today)
        _bump(ws, db, outcome)
        detail = refresh_meta(ws, today)
        questions = list(ws.draft_row.questions or [])
        user_row = S.record_message(db, ws, "user", body.text,
                                    {"attachment": body.file.name if body.file else None,
                                     "op_id": body.op_id})
        reply = compose_reply(outcome, detail, confirmed=ws.profile.confirmed,
                              questions=questions)
        assistant = S.record_message(db, ws, "assistant", reply,
                                     {"changed_summary": outcome.summaries,
                                      "rejections": outcome.rejections})
        response = state_payload(db, ws, today=today) | {
            "message_id": assistant.id,
            "user_message_id": user_row.id,
            "reply": reply,
            "changed_summary": outcome.summaries,
            "rejected_actions": outcome.rejections,
        }
        undoable = any(item.get("action") in UNDOABLE_ACTIONS for item in outcome.summaries)
        _log(db, ws.profile_id, body.op_id, "message",
             {"text": body.text, "has_file": body.file is not None}, response, before,
             undoable)
        db.commit()
        return 200, response
    except Exception:
        # 任何失败都不产生半完成写入：消息、动作与快照一起回滚。
        db.rollback()
        raise


def interpret(db: Session, ws: S.Workspace, text: str, outcome: X.Outcome, *,
              today: date) -> None:
    if not text:
        outcome.notes.append("没有收到内容：请粘贴报告文字或上传文件。")
        return
    pending = S.open_actions(db, ws.profile_id)
    if pending and _resolve_pending(db, ws, pending, text, outcome, today=today):
        return
    if P.is_undo(text):
        X.apply_action(db, ws, RawAction(type="undo"), outcome, today=today)
        return
    if P.is_confirmation(text):
        _confirm_or_explain(db, ws, outcome, today=today)
        return
    if P.is_cancellation(text):
        outcome.summaries.append({"action": "cancel"})
        return
    if _answer_questions(db, ws, text, outcome, today=today):
        return
    if P.is_delete(text):
        intent = P.parse_delete(text, today)
        X.apply_action(db, ws, RawAction(
            type="delete_visit", record_id=intent.record_id, value_text=text,
            date=intent.day.isoformat() if intent.day else None), outcome, today=today)
        return
    if P.is_modify(text) or P.is_unit_correction(text) or _states_unknown(text):
        _deterministic_update(db, ws, text, outcome, today=today)
        return
    has_context = bool(pending) or bool(ws.draft_row.questions)
    if _looks_like_report(text, today) or not has_context:
        # 资料正文复用既有提取能力：模型只能输出结构化字段，不能输出删除/执行类动作，
        # 因此资料里的指令不可能被当作授权。
        extraction = M.extract_document(ImportRequest(text=text))
        X.apply_extraction(db, ws, extraction["draft"], outcome, today=today)
        return
    # 有追问上下文且不像资料正文时，用模型兜底理解自由表达。
    _model_round(db, ws, text, outcome, today=today)


def _looks_like_report(text: str, today: date) -> bool:
    """粗判“资料正文”与“自由表达”：命中字段关键词或明确日期即按资料处理。"""
    if P.detect_fields(text):
        return True
    return P.parse_date(text, today) is not None


def _answer_questions(db: Session, ws: S.Workspace, text: str, outcome: X.Outcome, *,
                      today: date) -> bool:
    """把消息当作当前待追问字段的回答（确定性解析优先，解析失败才回退模型）。"""
    questions = list(ws.draft_row.questions or [])
    if not questions:
        return False
    mentioned = set(P.detect_fields(text))
    for item in questions:
        field = item.get("field") or ""
        record_id = item.get("record_id")
        if mentioned and field not in mentioned:
            continue
        if not _fits_question(field, text, today):
            continue
        if field == "chol_unit":
            action = RawAction(type="update_visit", record_id=record_id, field=field,
                               value_text=text, unit=P.parse_unit(text),
                               unit_intent="label")
        else:
            action = RawAction(type="update_visit" if record_id else "update_profile",
                               record_id=record_id, field=field, value_text=text)
        before = len(outcome.summaries)
        X.apply_action(db, ws, action, outcome, today=today)
        if len(outcome.summaries) > before:
            return True
    return False


def _fits_question(field: str, text: str, today: date) -> bool:
    """判断一条回答是否明确属于该追问字段；不确定时交给模型兜底。"""
    if P.is_unknown(text):
        return True
    if field == "chol_unit":
        return P.parse_unit(text) is not None
    parsed = P.parse_value_text(field, text, None, today)
    if parsed.value is None:
        return False
    return F.validate_field_value(field, parsed.value)[0]


def _deterministic_update(db: Session, ws: S.Workspace, text: str, outcome: X.Outcome, *,
                          today: date) -> None:
    intent = P.parse_modify(text, today)
    if intent is None:
        if _states_unknown(text):
            _apply_unknown_statement(db, ws, text, outcome, today=today)
            return
        _model_round(db, ws, text, outcome, today=today)
        return
    if intent.kind in ("unit_label", "unit_ambiguous") or intent.candidates == ("chol_unit",):
        unit_action = {"type": "update_visit", "field": "chol_unit", "value_text": text,
                       "unit": intent.unit,
                       "unit_intent": "label" if intent.kind == "unit_label" else "unknown"}
        if intent.kind == "unit_label":
            X.apply_action(db, ws, RawAction(**unit_action, date=None, record_id=None),
                           outcome, today=today)
            return
        records = X.scoped(ws)
        target = records[0][2] if records else {}
        X.ask_unit_intent(db, ws, RawAction(**unit_action, date=None, record_id=None),
                          "chol_unit", target, intent.unit or "",
                          F.unit_of("chol_unit", target), outcome)
        return
    if not intent.candidates:
        records = _target_records(ws, intent)
        candidates = _value_candidates(records)
        if not candidates:
            _model_round(db, ws, text, outcome, today=today)
            return
        X.ask_choose_field(db, ws, candidates, "要修改哪个指标？", outcome,
                           original={"type": "update_visit", "value_text": text,
                                     "unit": intent.unit, "unit_intent": "unknown"})
        return
    if len(intent.candidates) > 1:
        X.ask_choose_field(db, ws, intent.candidates, "要修改哪个指标？", outcome,
                           original={"type": "update_visit", "value_text": text,
                                     "unit": intent.unit, "unit_intent": "unknown"})
        return
    name = intent.candidates[0]
    action = RawAction(type="update_visit" if name in F.VISIT_FIELDS else "update_profile",
                       record_id=intent.record_id,
                       date=intent.day.isoformat() if intent.day else None,
                       field=name, value_text=text, unit=intent.unit,
                       unit_intent="label" if intent.kind == "unit_label" else "value")
    X.apply_action(db, ws, action, outcome, today=today)


def _target_records(ws: S.Workspace, intent: P.ModifyIntent) -> list[dict]:
    matches = X.locate(ws, record_id=intent.record_id, day=intent.day)
    if not matches and (intent.year or intent.month):
        matches = X.locate(ws, year=intent.year, month=intent.month)
    if not matches:
        matches = X.scoped(ws)
    return [visit for _, _, visit in matches]


def _states_unknown(text: str) -> bool:
    """用户点名了字段并明确表示“不知道”。"""
    return P.is_unknown(text) and bool(P.detect_fields(text))


def _apply_unknown_statement(db: Session, ws: S.Workspace, text: str, outcome: X.Outcome,
                             *, today: date) -> None:
    candidates = [name for name in P.detect_fields(text)
                  if name in {*F.VISIT_FIELDS, *F.PROFILE_FIELDS}]
    if not candidates:
        _model_round(db, ws, text, outcome, today=today)
        return
    if len(candidates) > 1:
        X.ask_choose_field(db, ws, tuple(candidates), "要把哪个字段记为“不知道”？", outcome,
                           original={"type": "update_visit", "value_text": text})
        return
    name = candidates[0]
    period = P.parse_period(text, today)
    action = RawAction(
        type="update_visit" if name in F.VISIT_FIELDS else "update_profile",
        record_id=P.detect_record_id(text),
        date=period.day.isoformat() if period and period.day else None,
        field=name, value_text=text)
    X.apply_action(db, ws, action, outcome, today=today)


def _value_candidates(records: list[dict]) -> tuple[str, ...]:
    if not records:
        return ()
    editable = [name for name in F.VISIT_FIELDS if name != "date"]
    shared = [name for name in editable
              if any(visit.get(name) is not None for visit in records)]
    return tuple(shared[:8])


def _confirm_or_explain(db: Session, ws: S.Workspace, outcome: X.Outcome, *,
                        today: date) -> None:
    data = ws.draft_data()
    missing = D.missing_paths(data)
    if not data.get("visits"):
        outcome.notes.append("当前没有待确认的草稿记录，请先上传或粘贴体检资料。")
        return
    if missing:
        labels = [item.split(".")[-1] for item in missing]
        outcome.notes.append("资料还有缺项（" + "、".join(labels) + "），补齐后才能确认。")
        return
    X.confirm_draft(db, ws, outcome, today=today)
    ws.set_draft(None)
    outcome.notes.append("已确认并写入历史档案，人体点亮与规划已按新版本更新。")


def _model_round(db: Session, ws: S.Workspace, text: str, outcome: X.Outcome, *,
                 today: date) -> None:
    state = {"profile": {"display_name": ws.profile.display_name,
                         "version": ws.profile.version},
             "confirmed": ws.profile.confirmed,
             "draft": ws.draft_row.data,
             "pending_questions": [item.payload.get("question")
                                   for item in S.open_actions(db, ws.profile_id)]}
    proposal = M.propose(text=text, state=state)
    if proposal.reply:
        outcome.notes.append(proposal.reply.strip())
    for question in proposal.questions:
        cleaned = question.strip()[:300]
        if not cleaned:
            continue
        S.queue_action(db, ws, "model_question",
                       {"action": "model_question", "question": cleaned})
        outcome.pending.append(cleaned)
    for action in proposal.actions:
        if action.type == "confirm":
            _confirm_or_explain(db, ws, outcome, today=today)
            continue
        if action.type == "cancel":
            outcome.summaries.append({"action": "cancel"})
            continue
        X.apply_action(db, ws, action, outcome, today=today)


# ------------------------------------------------------------------ 待追问动作


def _resolve_pending(db: Session, ws: S.Workspace, pending: list, text: str,
                     outcome: X.Outcome, *, today: date) -> bool:
    row = pending[0]
    kind = row.kind
    payload = row.payload or {}
    if kind == "model_question":
        S.resolve_action(db, row, "resolved")
        return False
    if kind == "question":
        return _answer_question(db, ws, row, payload, text, outcome, today=today)
    if kind == "choose_record":
        return _answer_choose_record(db, ws, row, payload, text, outcome, today=today)
    if kind == "choose_field":
        return _answer_choose_field(db, ws, row, payload, text, outcome, today=today)
    if kind == "choose_unit":
        return _answer_choose_unit(db, ws, row, payload, text, outcome, today=today)
    if kind == "duplicate_date":
        return _answer_duplicate(db, ws, row, payload, text, outcome, today=today)
    if kind == "delete_confirm":
        return _answer_delete(db, ws, row, payload, text, outcome)
    S.resolve_action(db, row, "cancelled")
    return False


def _answer_question(db: Session, ws: S.Workspace, row, payload: dict, text: str,
                     outcome: X.Outcome, *, today: date) -> bool:
    name = payload.get("field") or ""
    record_id = payload.get("record_id")
    if name == "chol_unit":
        action = RawAction(type="update_visit", record_id=record_id, field="chol_unit",
                           value_text=text, unit=P.parse_unit(text), unit_intent="label")
    else:
        action = RawAction(type="update_visit" if record_id else "update_profile",
                           record_id=record_id, field=name, value_text=text)
    if not _run_and_detect(db, ws, action, outcome, today=today):
        return False
    S.resolve_action(db, row, "resolved")
    return True


def _run_and_detect(db: Session, ws: S.Workspace, action: RawAction, outcome: X.Outcome,
                    *, today: date) -> bool:
    before = len(outcome.summaries) + len(outcome.rejections)
    X.apply_action(db, ws, action, outcome, today=today)
    return len(outcome.summaries) + len(outcome.rejections) > before


def _answer_choose_record(db: Session, ws: S.Workspace, row, payload: dict, text: str,
                          outcome: X.Outcome, *, today: date) -> bool:
    candidates = payload.get("candidates") or []
    match = _match_candidate(text, candidates, today)
    original = RawAction(**payload["original"]) if payload.get("original") else None
    if match is None or original is None:
        outcome.pending.append(payload.get("question") or "请说明要处理哪一条记录。")
        return True
    merged = original.model_dump() | {"record_id": match["record_id"], "date": None}
    if original.type == "delete_visit":
        X.apply_action(db, ws, RawAction(**merged), outcome, today=today)
    else:
        X.resolve_action(db, ws, RawAction(**merged), outcome, answer=text, today=today)
    S.resolve_action(db, row, "resolved")
    return True


def _match_candidate(text: str, candidates: list[dict], today: date) -> dict | None:
    record_id = P.detect_record_id(text)
    for candidate in candidates:
        if record_id and candidate.get("record_id") == record_id:
            return candidate
    day = P.parse_date(text, today)
    if day:
        for candidate in candidates:
            if candidate.get("date") == day.isoformat():
                return candidate
    period = P.parse_period(text, today)
    if period:
        matched = [candidate for candidate in candidates if candidate.get("date")
                   and date.fromisoformat(candidate["date"]).year == period.year
                   and (period.month is None
                        or date.fromisoformat(candidate["date"]).month == period.month)]
        if len(matched) == 1:
            return matched[0]
    number = P.parse_number(text)
    if number is not None and float(number).is_integer():
        index = int(number) - 1
        if 0 <= index < len(candidates):
            return candidates[index]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _answer_choose_field(db: Session, ws: S.Workspace, row, payload: dict, text: str,
                         outcome: X.Outcome, *, today: date) -> bool:
    candidates = tuple(payload.get("candidates") or ())
    detected = [name for name in P.detect_fields(text) if name in candidates]
    if len(detected) != 1:
        if len(candidates) == 1:
            detected = list(candidates)
        else:
            outcome.pending.append(payload.get("question") or "请说明要处理哪个指标。")
            return True
    original = RawAction(**payload["original"]) if payload.get("original") else None
    if original is None:
        S.resolve_action(db, row, "cancelled")
        return True
    merged = original.model_dump() | {"field": detected[0]}
    if merged.get("unit_intent") == "unknown" and P.parse_unit(text):
        merged["unit"] = P.parse_unit(text)
    X.resolve_action(db, ws, RawAction(**merged), outcome, answer=text, today=today)
    S.resolve_action(db, row, "resolved")
    return True


def _answer_choose_unit(db: Session, ws: S.Workspace, row, payload: dict, text: str,
                        outcome: X.Outcome, *, today: date) -> bool:
    lowered = text.lower()
    intent = None
    if any(word in lowered for word in ("换算", "转换", "按登记", "换一下", "换成数值")):
        intent = "value"
    elif any(word in lowered for word in ("标签", "写错", "抄错", "单位错", "数值不变",
                                          "不改数值", "只是单位")):
        intent = "label"
    unit = P.parse_unit(text) or payload.get("unit") or None
    if intent is None:
        outcome.pending.append(payload.get("question") or "请说明是改标签还是换算数值。")
        return True
    original = RawAction(**payload["original"]) if payload.get("original") else None
    if original is None:
        S.resolve_action(db, row, "cancelled")
        return True
    merged = original.model_dump() | {"unit_intent": intent}
    if unit:
        merged["unit"] = unit
    if not merged.get("field"):
        merged["field"] = payload.get("field")
    X.resolve_action(db, ws, RawAction(**merged), outcome, answer=text, today=today)
    S.resolve_action(db, row, "resolved")
    return True


def _answer_duplicate(db: Session, ws: S.Workspace, row, payload: dict, text: str,
                      outcome: X.Outcome, *, today: date) -> bool:
    lowered = text.lower()
    if any(word in lowered for word in ("覆盖", "更新成", "用新", "替换", "改成新")):
        X.apply_values_to_record(db, ws, payload.get("record_id"),
                                 payload.get("values") or {}, outcome)
        S.resolve_action(db, row, "resolved")
        return True
    if any(word in lowered for word in ("保留", "放弃", "丢弃", "算了", "不要", "不用")):
        outcome.summaries.append({"action": "cancel"})
        outcome.notes.append("已保留原记录，本次重复资料没有写入。")
        S.resolve_action(db, row, "resolved")
        return True
    if any(word in lowered for word in ("另存", "新增", "分开", "两条")):
        outcome.notes.append("同一天只能保留一条已确认记录；请选择覆盖该记录或保留原记录。")
        return True
    outcome.pending.append(payload.get("question") or "请选择覆盖、保留或放弃。")
    return True


def _answer_delete(db: Session, ws: S.Workspace, row, payload: dict, text: str,
                   outcome: X.Outcome) -> bool:
    if P.is_cancellation(text) or P.parse_bool(text) is False:
        outcome.summaries.append({"action": "cancel"})
        outcome.notes.append("已取消删除，资料保持不变。")
        S.resolve_action(db, row, "cancelled")
        return True
    if P.is_confirmation(text) or P.parse_bool(text) is True:
        X.execute_delete(db, ws, payload.get("record_id"), outcome)
        S.resolve_action(db, row, "resolved")
        return True
    outcome.pending.append(payload.get("question") or "确认删除吗？")
    return True


# ------------------------------------------------------------------ 档案级操作


def create_profile(db: Session, body: NewProfileRequest, *, today: date | None = None
                   ) -> tuple[int, dict]:
    today = today or date.today()
    option = body.save_current
    source_id = option.profile_id if option else None
    if option is not None and option.save == "cancel":
        if source_id:
            ws = S.load_workspace(db, source_id)
            return 200, state_payload(db, ws, today=today) | {"created": False,
                                                             "cancelled": True}
        return 200, {"created": False, "cancelled": True, "profile_id": None,
                     "display_name": None, "session_id": None,
                     "service_state": service_state()}
    replay = _replay(db, source_id or "", body.op_id)
    if replay is not None:
        return 200, replay
    if option is not None and option.save == "yes" and source_id:
        ws = S.load_workspace(db, source_id)
        if ws.profile.confirmed and (ws.profile.confirmed or {}).get("visits"):
            try:
                PL.generate_snapshot(db, ws, today=today)
                db.flush()
            except ConversationError as exc:
                db.rollback()
                raise InvalidInput("当前规划保存失败，仍留在原档案。",
                                   details={"error": "save_failed",
                                            "reason": exc.message}) from exc
            except Exception as exc:
                db.rollback()
                raise InvalidInput("当前规划保存失败，仍留在原档案。",
                                   details={"error": "save_failed"}) from exc
    profile = Profile(display_name=_display_name(db, body.display_name, today), version=0,
                      confirmed=None, analysis_stale=False)
    db.add(profile)
    db.flush()
    session = S.start_session(db, profile.id)
    draft_row = S.ensure_draft(db, profile.id)
    ws = S.Workspace(profile=profile, session=session, draft_row=draft_row)
    refresh_meta(ws, today)
    response = state_payload(db, ws, today=today) | {"created": True, "cancelled": False}
    _log(db, source_id or profile.id, body.op_id, "new_profile", body.model_dump(), response,
         S.snapshot_state(profile, draft_row), False)
    db.commit()
    return 201, response


def _display_name(db: Session, requested: str | None, today: date) -> str:
    base = (requested or f"体检档案 {today.isoformat()}").strip()[:60]
    if not base:
        base = f"体检档案 {today.isoformat()}"
    candidate = base
    index = 1
    while db.scalar(select(func.count()).select_from(Profile)
                    .where(Profile.display_name == candidate)):
        index += 1
        candidate = f"{base}（{index}）"
    return candidate


def confirm_profile(db: Session, profile_id: str, body, *, today: date | None = None
                    ) -> tuple[int, dict]:
    today = today or date.today()
    ws = S.load_workspace(db, profile_id)
    replay = _replay(db, profile_id, body.op_id)
    if replay is not None:
        return 200, replay
    _guard_version(ws, body.expected_version)
    before = S.snapshot_state(ws.profile, ws.draft_row)
    outcome = X.Outcome()
    try:
        X.confirm_draft(db, ws, outcome, today=today)
        ws.set_draft(None)
        _bump(ws, db, outcome)
        detail = refresh_meta(ws, today)
        reply = compose_reply(outcome, detail, confirmed=ws.profile.confirmed, questions=[])
        S.record_message(db, ws, "assistant", reply,
                         {"changed_summary": outcome.summaries, "kind": "confirm"})
        response = state_payload(db, ws, today=today) | {
            "reply": reply,
            "changed_summary": outcome.summaries,
            "rejected_actions": outcome.rejections,
        }
        _log(db, profile_id, body.op_id, "confirm", body.model_dump(), response, before, True)
        db.commit()
        return 200, response
    except ConversationError:
        db.rollback()
        raise


def restart_profile(db: Session, profile_id: str, body, *, today: date | None = None
                    ) -> tuple[int, dict]:
    today = today or date.today()
    ws = S.load_workspace(db, profile_id)
    replay = _replay(db, profile_id, body.op_id)
    if replay is not None:
        return 200, replay
    before = S.snapshot_state(ws.profile, ws.draft_row)
    S.expire_actions(db, profile_id)
    ws.session = S.start_session(db, profile_id)
    ws.set_draft(None)
    db.execute(update(ActionLog)
               .where(ActionLog.profile_id == profile_id, ActionLog.undoable.is_(True))
               .values(undone=True))
    refresh_meta(ws, today)
    response = state_payload(db, ws, today=today) | {
        "reply": "已重新开始整理：本轮未确认的草稿、附件与待执行动作已清空，"
                 "已确认资料和已保存规划保持不变。"}
    _log(db, profile_id, body.op_id, "restart", body.model_dump(), response, before, False)
    db.commit()
    return 200, response


def generate_plan(db: Session, profile_id: str, body, *, today: date | None = None
                  ) -> tuple[int, dict]:
    today = today or date.today()
    ws = S.load_workspace(db, profile_id)
    replay = _replay(db, profile_id, body.op_id)
    if replay is not None:
        return 200, replay
    _guard_version(ws, body.expected_version)
    before = S.snapshot_state(ws.profile, ws.draft_row)
    try:
        row = PL.generate_snapshot(db, ws, today=today)
        refresh_meta(ws, today)
        response = PL.plan_response(row) | {
            "profile_id": ws.profile_id,
            "display_name": ws.profile.display_name,
            "version": ws.profile.version,
            "analysis_stale": False,
            "missing": list(ws.draft_row.missing or []),
            "capabilities": list(ws.draft_row.capabilities or []),
            "system_availability": D.availability(
                D.system_detail(ws.profile.confirmed, today)),
        }
        _log(db, profile_id, body.op_id, "plan", body.model_dump(), response, before, False)
        db.commit()
        return 200, response
    except ConversationError:
        db.rollback()
        raise


def list_profiles(db: Session) -> list[dict]:
    rows = db.scalars(select(Profile).order_by(Profile.created_at.desc(),
                                               Profile.id.desc()).limit(100)).all()
    return [{"profile_id": row.id, "display_name": row.display_name, "version": row.version,
             "created_at": row.created_at.isoformat() if row.created_at else None,
             "has_confirmed": bool((row.confirmed or {}).get("visits")),
             "analysis_stale": bool(row.analysis_stale)} for row in rows]


def list_snapshots(db: Session, profile_id: str) -> list[dict]:
    ws = S.load_workspace(db, profile_id)
    rows = db.scalars(
        select(ArchiveSnapshot).where(ArchiveSnapshot.profile_id == profile_id)
        .order_by(ArchiveSnapshot.created_at.desc(), ArchiveSnapshot.id.desc()).limit(50)
    ).all()
    return [S.snapshot_summary(row) | {"display_name": ws.profile.display_name}
            for row in rows]


def get_snapshot(db: Session, profile_id: str, snapshot_id: str) -> dict:
    ws = S.load_workspace(db, profile_id)
    row = db.get(ArchiveSnapshot, snapshot_id)
    if row is None or row.profile_id != profile_id:
        raise ProfileNotFound("该规划快照不存在或不属于当前档案。")
    return PL.plan_response(row) | {
        "profile_id": ws.profile_id,
        "display_name": ws.profile.display_name,
        "read_only": True,
        "current_version": ws.profile.version,
        "is_latest_version": row.version == ws.profile.version,
    }


def restore_session(db: Session, profile_id: str, *, today: date | None = None) -> dict:
    ws = S.load_workspace(db, profile_id)
    return state_payload(db, ws, today=today or date.today())
