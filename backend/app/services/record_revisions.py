"""T02：业务记录的修订历史服务。

每次确认写入（新增/修改/删除）都落一条不可变修订记录，包含变更字段、前后快照、
来源与操作账号。查询按档案维度汇总，供历史详情与审计使用。
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AIReport,
    ExamHistory,
    HealthCheck,
    ImagingExam,
    LabMetric,
    Lesion,
    LesionObservation,
    LesionTrack,
    Patient,
    Recommendation,
    RecordRevision,
    RiskPrediction,
)
from app.models.base import Base

# 记录修订的实体类型名（对外稳定，勿随类名变化）。
REVISION_ENTITY_TYPES: dict[type[Base], str] = {
    Patient: "patient",
    HealthCheck: "health_check",
    LabMetric: "lab_metric",
    ImagingExam: "imaging_exam",
    ExamHistory: "exam_history",
    Lesion: "lesion",
    LesionTrack: "lesion_track",
    LesionObservation: "lesion_observation",
    Recommendation: "recommendation",
    RiskPrediction: "risk_prediction",
    AIReport: "ai_report",
}

# 快照中不参与差异比较、也不回传的字段。
IGNORED_SNAPSHOT_FIELDS = frozenset({"created_at"})


def entity_type_of(model: type[Base]) -> str:
    return REVISION_ENTITY_TYPES.get(model, model.__tablename__)


def jsonable(value: Any) -> Any:
    """把日期、枚举等转换为可写入 JSON 列的形式。"""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def snapshot(entity: Base) -> dict[str, Any]:
    return {
        column.name: jsonable(getattr(entity, column.name))
        for column in entity.__table__.columns
        if column.name not in IGNORED_SNAPSHOT_FIELDS
    }


def patient_id_of(db: Session, entity: Base) -> str | None:
    """把业务记录回溯到档案 ID；无法回溯时返回 None。"""

    if isinstance(entity, Patient):
        return entity.id
    direct = getattr(entity, "patient_id", None)
    if direct is not None:
        return direct
    if isinstance(entity, (LabMetric, ImagingExam, ExamHistory)):
        check = db.get(HealthCheck, entity.health_check_id)
        return None if check is None else check.patient_id
    if isinstance(entity, Lesion):
        exam = db.get(ImagingExam, entity.imaging_exam_id)
        if exam is None:
            return None
        check = db.get(HealthCheck, exam.health_check_id)
        return None if check is None else check.patient_id
    if isinstance(entity, LesionObservation):
        track = db.get(LesionTrack, entity.lesion_track_id)
        return None if track is None else track.patient_id
    return None


def diff_fields(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    if before is None or after is None:
        return []
    return sorted(
        key
        for key in set(before) | set(after)
        if before.get(key) != after.get(key) and key not in {"revision_no"}
    )


class RecordRevisionService:
    """写入修订记录；不提交事务，由调用方决定事务边界。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        entity: Base,
        *,
        action: str,
        before: dict[str, Any] | None = None,
        source_kind: str = "manual",
        source_ref: str | None = None,
        actor_account_id: str | None = None,
        note: str | None = None,
    ) -> RecordRevision:
        entity_type = entity_type_of(type(entity))
        current = self.next_revision_no(entity_type, entity.id)
        if hasattr(entity, "revision_no"):
            entity.revision_no = current
        after = snapshot(entity)
        revision = RecordRevision(
            patient_id=patient_id_of(self.db, entity),
            entity_type=entity_type,
            entity_id=entity.id,
            revision_no=current,
            action=action,
            changed_fields=diff_fields(before, after),
            before=before,
            after=after,
            source_kind=source_kind,
            source_ref=source_ref,
            actor_account_id=actor_account_id,
            note=note,
        )
        self.db.add(revision)
        return revision

    def next_revision_no(self, entity_type: str, entity_id: str) -> int:
        latest = self.db.scalar(
            select(func.max(RecordRevision.revision_no)).where(
                RecordRevision.entity_type == entity_type,
                RecordRevision.entity_id == entity_id,
            )
        )
        return int(latest or 0) + 1

    def record_deleted(
        self,
        *,
        entity_type: str,
        entity_id: str,
        before: dict[str, Any],
        patient_id: str | None,
        actor_account_id: str | None = None,
        source_kind: str = "manual",
        source_ref: str | None = None,
        note: str | None = None,
    ) -> RecordRevision:
        """记录一次删除；被删记录已不在库中，只保存删除前快照。"""

        revision = RecordRevision(
            patient_id=patient_id,
            entity_type=entity_type,
            entity_id=entity_id,
            revision_no=self.next_revision_no(entity_type, entity_id),
            action="delete",
            changed_fields=sorted(before),
            before=before,
            after=None,
            source_kind=source_kind,
            source_ref=source_ref,
            actor_account_id=actor_account_id,
            note=note,
        )
        self.db.add(revision)
        return revision

    def history(
        self,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        patient_id: str | None = None,
        limit: int = 100,
    ) -> list[RecordRevision]:
        statement = select(RecordRevision)
        if entity_type is not None:
            statement = statement.where(RecordRevision.entity_type == entity_type)
        if entity_id is not None:
            statement = statement.where(RecordRevision.entity_id == entity_id)
        if patient_id is not None:
            statement = statement.where(RecordRevision.patient_id == patient_id)
        statement = statement.order_by(
            RecordRevision.created_at.desc(), RecordRevision.revision_no.desc()
        ).limit(limit)
        return list(self.db.scalars(statement))
