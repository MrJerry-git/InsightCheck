"""会话/草稿/档案的读取与序列化，保证档案之间完全隔离。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.conversation import (
    ActionLog,
    ArchiveSnapshot,
    ConversationMessage,
    ConversationSession,
    PendingAction,
    Profile,
    ProfileDraft,
)
from app.services.conversation import draft as D
from app.services.conversation.errors import ProfileNotFound

MESSAGE_WINDOW = 50

_clock_lock = threading.Lock()
_last_stamp = datetime.now(UTC)


def now() -> datetime:
    """严格递增的时间戳：保证同一秒内多行写入的顺序稳定（列表按插入顺序回放）。"""
    global _last_stamp
    with _clock_lock:
        stamp = datetime.now(UTC)
        if stamp <= _last_stamp:
            stamp = _last_stamp + timedelta(microseconds=1)
        _last_stamp = stamp
        return stamp


@dataclass
class Workspace:
    profile: Profile
    session: ConversationSession
    draft_row: ProfileDraft

    @property
    def profile_id(self) -> str:
        return self.profile.id

    @property
    def session_id(self) -> str:
        return self.session.id

    def confirmed(self) -> dict | None:
        return self.profile.confirmed

    def draft_data(self) -> dict:
        return D.normalize(self.draft_row.data)

    def set_draft(self, data: dict | None) -> None:
        self.draft_row.data = data
        self.draft_row.version = (self.draft_row.version or 0) + 1


def get_profile(db: Session, profile_id: str) -> Profile:
    profile = db.get(Profile, profile_id)
    if profile is None:
        raise ProfileNotFound("档案不存在或已被移除，请返回列表重新选择。")
    return profile


def active_session(db: Session, profile_id: str, *, create: bool = False) -> ConversationSession:
    session = db.scalars(
        select(ConversationSession)
        .where(ConversationSession.profile_id == profile_id, ConversationSession.active.is_(True))
        .order_by(ConversationSession.created_at.desc(), ConversationSession.id.desc())
    ).first()
    if session is None:
        if not create:
            raise ProfileNotFound("该档案当前没有可用会话。")
        session = start_session(db, profile_id)
    return session


def start_session(db: Session, profile_id: str) -> ConversationSession:
    db.execute(
        update(ConversationSession)
        .where(ConversationSession.profile_id == profile_id,
               ConversationSession.active.is_(True))
        .values(active=False, ended_at=datetime.now(UTC))
    )
    session = ConversationSession(profile_id=profile_id, active=True)
    db.add(session)
    db.flush()
    return session


def ensure_draft(db: Session, profile_id: str) -> ProfileDraft:
    row = db.scalars(
        select(ProfileDraft).where(ProfileDraft.profile_id == profile_id)
    ).first()
    if row is None:
        row = ProfileDraft(profile_id=profile_id, version=0, data=None, missing=[],
                           questions=[], capabilities=[])
        db.add(row)
        db.flush()
    return row


def load_workspace(db: Session, profile_id: str, *, create_session: bool = True) -> Workspace:
    profile = get_profile(db, profile_id)
    session = active_session(db, profile_id, create=create_session)
    return Workspace(profile=profile, session=session, draft_row=ensure_draft(db, profile_id))


def open_actions(db: Session, profile_id: str) -> list[PendingAction]:
    return list(db.scalars(
        select(PendingAction)
        .where(PendingAction.profile_id == profile_id, PendingAction.status == "open")
        .order_by(PendingAction.created_at.asc(), PendingAction.id.asc())
    ))


def queue_action(db: Session, ws: Workspace, kind: str, payload: dict) -> PendingAction:
    row = PendingAction(profile_id=ws.profile_id, session_id=ws.session_id, kind=kind,
                        payload=payload, status="open", created_at=now())
    db.add(row)
    db.flush()
    return row


def resolve_action(db: Session, action: PendingAction, status: str) -> None:
    action.status = status
    action.resolved_at = datetime.now(UTC)
    db.add(action)


def expire_actions(db: Session, profile_id: str) -> None:
    db.execute(
        update(PendingAction)
        .where(PendingAction.profile_id == profile_id, PendingAction.status == "open")
        .values(status="expired", resolved_at=datetime.now(UTC))
    )


def record_message(db: Session, ws: Workspace, role: str, text: str,
                   payload: dict) -> ConversationMessage:
    row = ConversationMessage(profile_id=ws.profile_id, session_id=ws.session_id, role=role,
                              text=text, payload=payload, created_at=now())
    db.add(row)
    db.flush()
    return row


def recent_messages(db: Session, profile_id: str, session_id: str | None = None,
                    limit: int = MESSAGE_WINDOW) -> list[ConversationMessage]:
    query = select(ConversationMessage).where(ConversationMessage.profile_id == profile_id)
    if session_id:
        query = query.where(ConversationMessage.session_id == session_id)
    rows = list(db.scalars(query.order_by(ConversationMessage.created_at.desc(),
                                          ConversationMessage.id.desc()).limit(limit)))
    return list(reversed(rows))


def find_log(db: Session, profile_id: str, op_id: str) -> ActionLog | None:
    return db.scalars(
        select(ActionLog).where(ActionLog.profile_id == profile_id, ActionLog.op_id == op_id)
    ).first()


def last_undoable(db: Session, profile_id: str) -> ActionLog | None:
    return db.scalars(
        select(ActionLog)
        .where(ActionLog.profile_id == profile_id, ActionLog.undoable.is_(True),
               ActionLog.undone.is_(False))
        .order_by(ActionLog.created_at.desc(), ActionLog.id.desc())
    ).first()


def snapshot_state(profile: Profile, draft_row: ProfileDraft) -> dict:
    return {"confirmed": profile.confirmed, "version": profile.version,
            "analysis_stale": profile.analysis_stale, "draft": draft_row.data,
            "draft_version": draft_row.version}


def restore_state(profile: Profile, draft_row: ProfileDraft, state: dict) -> None:
    profile.confirmed = state.get("confirmed")
    profile.version = int(state.get("version") or 0)
    profile.analysis_stale = bool(state.get("analysis_stale"))
    draft_row.data = state.get("draft")
    draft_row.version = (draft_row.version or 0) + 1


def pending_payload(db: Session, profile_id: str) -> list[dict]:
    return [
        {"action_id": row.id, "action": row.payload.get("action", row.kind),
         "field": row.payload.get("field"), "record_id": row.payload.get("record_id"),
         "target": row.payload.get("target"), "question": row.payload.get("question"),
         "candidates": row.payload.get("candidates"), "purpose": row.payload.get("purpose")}
        for row in open_actions(db, profile_id)
    ]


def current_snapshot(db: Session, profile_id: str) -> ArchiveSnapshot | None:
    return db.scalars(
        select(ArchiveSnapshot)
        .where(ArchiveSnapshot.profile_id == profile_id, ArchiveSnapshot.status == "current")
        .order_by(ArchiveSnapshot.created_at.desc(), ArchiveSnapshot.id.desc())
    ).first()


def mark_snapshots_stale(db: Session, profile_id: str) -> int:
    return db.execute(
        update(ArchiveSnapshot)
        .where(ArchiveSnapshot.profile_id == profile_id, ArchiveSnapshot.status == "current")
        .values(status="stale")
    ).rowcount or 0


def snapshot_summary(row: ArchiveSnapshot) -> dict:
    payload = row.payload or {}
    return {"snapshot_id": row.id, "snapshot_version": row.version, "status": row.status,
            "created_at": _iso(row.created_at), "profile_id": row.profile_id,
            "planning_window": payload.get("planning_window"),
            "recommendation_count": len(payload.get("recommendations") or [])}


def message_summary(row: ConversationMessage) -> dict:
    payload = row.payload or {}
    return {"message_id": row.id, "role": row.role, "text": row.text,
            "created_at": _iso(row.created_at),
            "changed_summary": payload.get("changed_summary") or [],
            "attachment": payload.get("attachment")}


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None
