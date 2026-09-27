"""T08：管理操作审计查询。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, PlanRevision, RecordRevision


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        action: str,
        entity_type: str,
        summary: str,
        entity_id: str | None = None,
        patient_id: str | None = None,
        payload: dict[str, Any] | None = None,
        actor_account_id: str | None = None,
        actor_username: str = "anonymous",
    ) -> AuditEvent:
        event = AuditEvent(
            actor_account_id=actor_account_id,
            actor_username=actor_username,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            patient_id=patient_id,
            summary=summary[:1000],
            payload=payload or {},
        )
        self.db.add(event)
        return event

    def events(self, *, limit: int = 100, action: str | None = None) -> list[AuditEvent]:
        statement = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
        if action is not None:
            statement = statement.where(AuditEvent.action == action)
        return list(self.db.scalars(statement))

    def combined(
        self,
        *,
        limit: int = 100,
        source: str = "all",
        patient_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """合并管理审计与业务修订；两者语义不同，返回时用 ``source`` 区分。"""

        events: list[dict[str, Any]] = []
        if source in {"all", "admin"}:
            events.extend(
                {
                    "source": "admin",
                    "action": event.action,
                    "entity_type": event.entity_type,
                    "entity_id": event.entity_id,
                    "patient_id": event.patient_id,
                    "summary": event.summary,
                    "actor_username": event.actor_username,
                    "actor_account_id": event.actor_account_id,
                    "created_at": event.created_at,
                    "detail": event.payload,
                }
                for event in self.events(limit=limit)
            )
        if source in {"all", "records"}:
            statement = (
                select(RecordRevision)
                .order_by(RecordRevision.created_at.desc())
                .limit(limit)
            )
            if patient_id is not None:
                statement = statement.where(RecordRevision.patient_id == patient_id)
            events.extend(
                {
                    "source": "records",
                    "action": revision.action,
                    "entity_type": revision.entity_type,
                    "entity_id": revision.entity_id,
                    "patient_id": revision.patient_id,
                    "summary": (
                        f"{revision.entity_type} {revision.action}"
                        f"（修订 {revision.revision_no}）"
                    ),
                    "actor_username": None,
                    "actor_account_id": revision.actor_account_id,
                    "created_at": revision.created_at,
                    "detail": {
                        "changed_fields": revision.changed_fields,
                        "source_kind": revision.source_kind,
                        "source_ref": revision.source_ref,
                    },
                }
                for revision in self.db.scalars(statement)
            )
        if source in {"all", "plans"}:
            statement = (
                select(PlanRevision).order_by(PlanRevision.created_at.desc()).limit(limit)
            )
            events.extend(
                {
                    "source": "plans",
                    "action": revision.action,
                    "entity_type": "plan",
                    "entity_id": revision.plan_id,
                    "patient_id": None,
                    "summary": f"方案修订 {revision.revision_no}：{revision.reason}"[:1000],
                    "actor_username": None,
                    "actor_account_id": revision.created_by_account_id,
                    "created_at": revision.created_at,
                    "detail": {"price_catalog_version": revision.price_catalog_version},
                }
                for revision in self.db.scalars(statement)
            )
        events.sort(key=lambda item: item["created_at"] or 0, reverse=True)
        return events[:limit]
