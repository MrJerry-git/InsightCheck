"""档案归属过滤（T01）。

业务表通过外键回溯到 ``patients``，非管理员账号只能看见自己名下档案的数据。
目录类资源（体检项目、指标字典、医学规则、价格）是全局配置，不做归属过滤。
"""

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, can_access_patient
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
    RiskPrediction,
)
from app.models.base import Base

# 直接带 patient_id 的业务表。
DIRECT_PATIENT_MODELS: tuple[type[Base], ...] = (
    HealthCheck,
    LesionTrack,
    Recommendation,
    RiskPrediction,
    AIReport,
)

# 需要通过父表回溯到 patient 的业务表。
BY_HEALTH_CHECK_MODELS: tuple[type[Base], ...] = (LabMetric, ImagingExam, ExamHistory)
BY_LESION_TRACK_MODELS: tuple[type[Base], ...] = (LesionObservation,)

PATIENT_SCOPE_MODELS: frozenset[type[Base]] = frozenset(
    (*DIRECT_PATIENT_MODELS, *BY_HEALTH_CHECK_MODELS, *BY_LESION_TRACK_MODELS, Lesion)
)


def scope_statement(statement: Select, model: type[Base], principal: Principal) -> Select:
    """把查询限制在调用主体可见的档案范围；管理员与开发模式不限制。"""

    if not principal.authenticated or principal.is_admin or model not in PATIENT_SCOPE_MODELS:
        return statement
    if model in DIRECT_PATIENT_MODELS:
        statement = statement.join(Patient, model.patient_id == Patient.id)
    elif model in BY_HEALTH_CHECK_MODELS:
        statement = statement.join(
            HealthCheck, model.health_check_id == HealthCheck.id
        ).join(Patient, HealthCheck.patient_id == Patient.id)
    elif model in BY_LESION_TRACK_MODELS:
        statement = statement.join(
            LesionTrack, model.lesion_track_id == LesionTrack.id
        ).join(Patient, LesionTrack.patient_id == Patient.id)
    elif model is Lesion:
        statement = (
            statement.join(ImagingExam, Lesion.imaging_exam_id == ImagingExam.id)
            .join(HealthCheck, ImagingExam.health_check_id == HealthCheck.id)
            .join(Patient, HealthCheck.patient_id == Patient.id)
        )
    return statement.where(Patient.owner_account_id == principal.account_id)


def is_patient_scoped(model: type[Base]) -> bool:
    return model in PATIENT_SCOPE_MODELS


def get_visible_entity(
    db: Session, model: type[Base], principal: Principal, entity_id: str
) -> Base:
    """按归属取单条记录；不可见时不区分“不存在/无权”，统一 404。"""

    statement = scope_statement(select(model), model, principal).where(model.id == entity_id)
    entity = db.scalar(statement)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记录不存在或无权访问")
    return entity


def patient_id_for_values(db: Session, model: type[Base], values: dict[str, Any]) -> str | None:
    """从写入内容解析目标档案 ID；无法解析时返回 None，交给外键与校验处理。"""

    if model in (HealthCheck, LesionTrack, Recommendation, RiskPrediction, AIReport):
        return values.get("patient_id")
    if model in (LabMetric, ImagingExam, ExamHistory):
        check = db.get(HealthCheck, values.get("health_check_id"))
        return None if check is None else check.patient_id
    if model is Lesion:
        exam = db.get(ImagingExam, values.get("imaging_exam_id"))
        if exam is None:
            return None
        check = db.get(HealthCheck, exam.health_check_id)
        return None if check is None else check.patient_id
    if model is LesionObservation:
        track = db.get(LesionTrack, values.get("lesion_track_id"))
        return None if track is None else track.patient_id
    return None


def ensure_patient_write_scope(
    db: Session, model: type[Base], principal: Principal, values: dict[str, Any]
) -> None:
    """写入前校验目标档案归属，避免在他人档案下新增记录。"""

    if not principal.authenticated or principal.is_admin or model not in PATIENT_SCOPE_MODELS:
        return
    patient_id = patient_id_for_values(db, model, values)
    if patient_id is None:
        return
    patient = db.get(Patient, patient_id)
    if patient is None or not can_access_patient(principal, patient):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该账号无权在该档案下写入记录",
        )
