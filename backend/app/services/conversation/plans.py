"""规划联动：快照、分系统归属与整体汇总去重。

复用既有 prevention.assess()，不生成新的疾病概率或医学结论；
只补充“这条建议属于哪个系统/跨系统关联”的稳定字段，供前端分系统与整体页使用。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.conversation import ArchiveSnapshot
from app.schemas.prevention import PreventionRequest
from app.services.conversation import draft as D
from app.services.conversation import executor as X
from app.services.conversation import fields as F
from app.services.conversation.errors import ValidationFailed
from app.services.conversation.store import (
    Workspace,
    mark_snapshots_stale,
    snapshot_summary,
)
from app.services.prevention import assess

CODE_SYSTEMS: dict[str, tuple[str, ...]] = {
    "bp": ("cardiovascular",),
    "lipids": ("cardiovascular",),
    "glucose": ("glucose_metabolism",),
    "kidney": ("renal",),
    "clinical": ("cardiovascular", "glucose_metabolism", "renal"),
}


def _latest(payload: dict) -> dict:
    visits = payload.get("input", {}).get("visits") or []
    return max(visits, key=lambda visit: visit["date"]) if visits else {}


def related_systems(code: str, payload: dict) -> tuple[list[str], list[str]]:
    """返回 (归属系统, 关联说明)。"""
    systems = list(CODE_SYSTEMS.get(code, ("cardiovascular",)))
    latest = _latest(payload)
    notes: list[str] = []
    if code == "kidney" and latest.get("dm"):
        systems.append("glucose_metabolism")
        notes.append("同时涉及血糖与代谢（糖尿病病史）")
    if code == "glucose" and (latest.get("egfr") or 999) < 60:
        systems.append("renal")
        notes.append("同时涉及肾功能（eGFR 偏低）")
    if code == "lipids" and latest.get("statin"):
        notes.append("同时涉及既有他汀用药（本系统不调整药物）")
    return list(dict.fromkeys(systems)), notes


def attribute_plan(payload: dict) -> dict:
    """补充稳定归属字段；同一建议跨系统只保留一条并附关联说明。"""
    items = payload.get("recommendations") or []
    scope_index: dict[str, list[str]] = {system: [] for system in F.SYSTEM_FIELDS}
    overall: list[dict] = []
    seen: dict[str, dict] = {}
    for item in items:
        systems, notes = related_systems(item["code"], payload)
        item["systems"] = systems
        item["related_systems_note"] = "；".join(notes) if notes else None
        item.setdefault("due_date", None)
        for system in systems:
            scope_index.setdefault(system, []).append(item["code"])
        if item["code"] in seen:
            existing = seen[item["code"]]
            existing["systems"] = list(dict.fromkeys([*existing["systems"], *systems]))
            merged_notes = [note for note in [existing.get("related_systems_note"),
                                              item.get("related_systems_note")] if note]
            existing["related_systems_note"] = "；".join(dict.fromkeys(merged_notes)) or None
            continue
        entry = {**item, "deduplicated": False}
        seen[item["code"]] = entry
        overall.append(entry)
    payload["recommendations"] = items
    payload["scope_index"] = scope_index
    payload["overall"] = overall
    payload["system_labels"] = F.SYSTEM_LABELS
    return payload


def build_plan(confirmed: dict, *, today: date) -> dict:
    """基于当前已确认版本评估；资料不足时明确缺项，不补默认值。"""
    missing = D.missing_paths(confirmed)
    if not confirmed or not confirmed.get("visits"):
        raise ValidationFailed("还没有已确认的资料，无法生成规划。", errors=[
            {"loc": ["confirmed"], "msg": "需要先确认至少一条检查记录"}],
            missing=["visits"], capabilities=["当前没有已确认资料。"])
    try:
        request = X.build_request(confirmed, label=confirmed.get("label") or "体检档案",
                                  today=today)
    except Exception as exc:  # pragma: no cover - 由 confirm 阶段保证，防御性分支
        errors = [{"loc": ["confirmed"], "msg": str(exc)}]
        raise ValidationFailed("已确认资料未通过校验，无法生成规划。", errors=errors,
                               missing=missing) from exc
    payload = assess(_request_with_freshness(request, today))
    return attribute_plan(payload)


def _request_with_freshness(request: PreventionRequest, today: date) -> PreventionRequest:
    # 评估日期始终使用“当前日期”，避免旧快照冒充最新结果。
    return request.model_copy(update={"as_of": today})


def generate_snapshot(db: Session, ws: Workspace, *, today: date) -> ArchiveSnapshot:
    payload = build_plan(ws.profile.confirmed or {}, today=today)
    mark_snapshots_stale(db, ws.profile_id)
    payload["profile_id"] = ws.profile_id
    payload["profile_display_name"] = ws.profile.display_name
    payload["snapshot_version"] = ws.profile.version
    row = ArchiveSnapshot(profile_id=ws.profile_id, version=ws.profile.version,
                          status="current", payload=payload)
    db.add(row)
    db.flush()
    ws.profile.analysis_stale = False
    return row


def plan_response(row: ArchiveSnapshot) -> dict:
    return {"snapshot_id": row.id, "snapshot_version": row.version,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "status": row.status, **(row.payload or {})}


__all__ = ["attribute_plan", "build_plan", "generate_snapshot", "plan_response",
           "related_systems", "snapshot_summary"]
