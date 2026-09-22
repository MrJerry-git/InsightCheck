from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    Principal,
    ensure_patient_access,
    get_db,
    require_admin,
    require_write_access,
    scope_patient_statement,
)
from app.api.ownership import (
    ensure_patient_write_scope,
    get_visible_entity,
    is_patient_scoped,
)
from app.models import (
    AIReport,
    ExamHistory,
    ExamItem,
    HealthCheck,
    ImagingExam,
    LabMetric,
    Lesion,
    LesionObservation,
    LesionTrack,
    MedicalRule,
    MetricDictionary,
    Patient,
    Recommendation,
    RecommendationItem,
    RiskPrediction,
)
from app.models.base import Base
from app.schemas.domain import (
    AIReportCreate,
    AIReportRead,
    AIReportUpdate,
    ExamHistoryCreate,
    ExamHistoryRead,
    ExamHistoryUpdate,
    ExamItemCreate,
    ExamItemRead,
    ExamItemUpdate,
    HealthCheckCreate,
    HealthCheckRead,
    HealthCheckUpdate,
    ImagingExamCreate,
    ImagingExamRead,
    ImagingExamUpdate,
    LabMetricCreate,
    LabMetricRead,
    LabMetricUpdate,
    LesionCreate,
    LesionObservationCreate,
    LesionObservationRead,
    LesionObservationUpdate,
    LesionRead,
    LesionTrackCreate,
    LesionTrackRead,
    LesionTrackUpdate,
    LesionUpdate,
    MedicalRuleCreate,
    MedicalRuleRead,
    MedicalRuleUpdate,
    MetricDictionaryCreate,
    MetricDictionaryRead,
    MetricDictionaryUpdate,
    PatientCreate,
    PatientRead,
    PatientUpdate,
    RecommendationCreate,
    RecommendationItemCreate,
    RecommendationItemRead,
    RecommendationItemUpdate,
    RecommendationRead,
    RecommendationUpdate,
    RiskPredictionCreate,
    RiskPredictionRead,
    RiskPredictionUpdate,
)
from app.services.crud import CrudService, EntityConflictError, EntityNotFoundError


@dataclass(frozen=True)
class CrudSpec:
    resource: str
    path: str
    model: type[Base]
    create_schema: type[BaseModel]
    update_schema: type[BaseModel]
    read_schema: type[BaseModel]
    # 写入权限：目录类配置只有管理员能改；业务数据由写入角色维护，并按档案归属过滤。
    admin_only_write: bool = False


CRUD_SPECS = (
    CrudSpec("patient", "/patients", Patient, PatientCreate, PatientUpdate, PatientRead),
    CrudSpec(
        "health_check",
        "/health-checks",
        HealthCheck,
        HealthCheckCreate,
        HealthCheckUpdate,
        HealthCheckRead,
    ),
    CrudSpec(
        "metric_dictionary",
        "/metric-dictionaries",
        MetricDictionary,
        MetricDictionaryCreate,
        MetricDictionaryUpdate,
        MetricDictionaryRead,
        admin_only_write=True,
    ),
    CrudSpec(
        "lab_metric", "/lab-metrics", LabMetric, LabMetricCreate, LabMetricUpdate, LabMetricRead
    ),
    CrudSpec(
        "imaging_exam",
        "/imaging-exams",
        ImagingExam,
        ImagingExamCreate,
        ImagingExamUpdate,
        ImagingExamRead,
    ),
    CrudSpec("lesion", "/lesions", Lesion, LesionCreate, LesionUpdate, LesionRead),
    CrudSpec(
        "lesion_track",
        "/lesion-tracks",
        LesionTrack,
        LesionTrackCreate,
        LesionTrackUpdate,
        LesionTrackRead,
    ),
    CrudSpec(
        "lesion_observation",
        "/lesion-observations",
        LesionObservation,
        LesionObservationCreate,
        LesionObservationUpdate,
        LesionObservationRead,
    ),
    CrudSpec(
        "exam_item",
        "/exam-items",
        ExamItem,
        ExamItemCreate,
        ExamItemUpdate,
        ExamItemRead,
        admin_only_write=True,
    ),
    CrudSpec(
        "exam_history",
        "/exam-histories",
        ExamHistory,
        ExamHistoryCreate,
        ExamHistoryUpdate,
        ExamHistoryRead,
    ),
    CrudSpec(
        "medical_rule",
        "/medical-rules",
        MedicalRule,
        MedicalRuleCreate,
        MedicalRuleUpdate,
        MedicalRuleRead,
        admin_only_write=True,
    ),
    CrudSpec(
        "risk_prediction",
        "/risk-predictions",
        RiskPrediction,
        RiskPredictionCreate,
        RiskPredictionUpdate,
        RiskPredictionRead,
    ),
    CrudSpec(
        "recommendation",
        "/recommendations",
        Recommendation,
        RecommendationCreate,
        RecommendationUpdate,
        RecommendationRead,
    ),
    CrudSpec(
        "recommendation_item",
        "/recommendation-items",
        RecommendationItem,
        RecommendationItemCreate,
        RecommendationItemUpdate,
        RecommendationItemRead,
    ),
    CrudSpec("ai_report", "/ai-reports", AIReport, AIReportCreate, AIReportUpdate, AIReportRead),
)


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, EntityNotFoundError):
        raise HTTPException(status_code=404, detail="记录不存在") from exc
    if isinstance(exc, EntityConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


def build_crud_router(spec: CrudSpec) -> APIRouter:
    router = APIRouter(prefix=spec.path, tags=[spec.resource])
    guard = require_admin if spec.admin_only_write else require_write_access

    def create(
        payload: Any,
        principal: Principal = Depends(guard),  # noqa: B008
        db: Session = Depends(get_db),  # noqa: B008
    ) -> Any:
        values = payload.model_dump()
        if spec.model is Patient and principal.account_id is not None:
            # 新建档案自动归属当前账号，避免出现无主档案。
            values["owner_account_id"] = principal.account_id
        ensure_patient_write_scope(db, spec.model, principal, values)
        try:
            return CrudService(db, spec.model).create_values(values)
        except (EntityConflictError, EntityNotFoundError) as exc:
            _raise_http_error(exc)

    create.__name__ = f"create_{spec.resource}"
    create.__annotations__["payload"] = spec.create_schema
    create.__annotations__["return"] = spec.read_schema
    create.__annotations__["principal"] = Principal
    router.add_api_route(
        "",
        create,
        methods=["POST"],
        response_model=spec.read_schema,
        status_code=status.HTTP_201_CREATED,
        operation_id=f"create_{spec.resource}",
    )

    def list_entities(
        principal: Principal = Depends(require_write_access),  # noqa: B008
        offset: int = Query(default=0, ge=0),  # noqa: B008
        limit: int = Query(default=100, ge=1, le=500),  # noqa: B008
        db: Session = Depends(get_db),  # noqa: B008
    ) -> Any:
        if spec.model is Patient:
            return list(
                db.scalars(
                    scope_patient_statement(select(Patient), principal)
                    .order_by(Patient.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
        return CrudService(db, spec.model).list(
            offset=offset, limit=limit, scope=(spec.model, principal)
        )

    list_entities.__name__ = f"list_{spec.resource}"
    list_entities.__annotations__["return"] = list[spec.read_schema]  # type: ignore[valid-type]
    list_entities.__annotations__["principal"] = Principal
    router.add_api_route(
        "",
        list_entities,
        methods=["GET"],
        response_model=list[spec.read_schema],  # type: ignore[valid-type]
        operation_id=f"list_{spec.resource}",
    )

    def get_entity(
        entity_id: str,
        principal: Principal = Depends(require_write_access),  # noqa: B008
        db: Session = Depends(get_db),  # noqa: B008
    ) -> Any:
        if spec.model is Patient:
            return ensure_patient_access(db, principal, entity_id)
        if is_patient_scoped(spec.model):
            return get_visible_entity(db, spec.model, principal, entity_id)
        try:
            return CrudService(db, spec.model).get(entity_id)
        except (EntityConflictError, EntityNotFoundError) as exc:
            _raise_http_error(exc)

    get_entity.__name__ = f"get_{spec.resource}"
    get_entity.__annotations__["return"] = spec.read_schema
    get_entity.__annotations__["principal"] = Principal
    router.add_api_route(
        "/{entity_id}",
        get_entity,
        methods=["GET"],
        response_model=spec.read_schema,
        operation_id=f"get_{spec.resource}",
    )

    def update_entity(
        entity_id: str,
        payload: Any,
        principal: Principal = Depends(guard),  # noqa: B008
        db: Session = Depends(get_db),  # noqa: B008
    ) -> Any:
        if spec.model is Patient:
            ensure_patient_access(db, principal, entity_id)
        if is_patient_scoped(spec.model):
            get_visible_entity(db, spec.model, principal, entity_id)
            # 也校验写入后的父级归属，防止把记录改挂到他人档案下。
            ensure_patient_write_scope(
                db, spec.model, principal, payload.model_dump(exclude_unset=True)
            )
        try:
            return CrudService(db, spec.model).update(entity_id, payload)
        except (EntityConflictError, EntityNotFoundError) as exc:
            _raise_http_error(exc)

    update_entity.__name__ = f"update_{spec.resource}"
    update_entity.__annotations__["payload"] = spec.update_schema
    update_entity.__annotations__["return"] = spec.read_schema
    update_entity.__annotations__["principal"] = Principal
    router.add_api_route(
        "/{entity_id}",
        update_entity,
        methods=["PATCH"],
        response_model=spec.read_schema,
        operation_id=f"update_{spec.resource}",
    )

    def delete_entity(
        entity_id: str,
        principal: Principal = Depends(guard),  # noqa: B008
        db: Session = Depends(get_db),  # noqa: B008
    ) -> Response:
        if spec.model is Patient:
            ensure_patient_access(db, principal, entity_id)
        if is_patient_scoped(spec.model):
            get_visible_entity(db, spec.model, principal, entity_id)
        try:
            CrudService(db, spec.model).delete(entity_id)
        except (EntityConflictError, EntityNotFoundError) as exc:
            _raise_http_error(exc)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    delete_entity.__name__ = f"delete_{spec.resource}"
    delete_entity.__annotations__["principal"] = Principal
    router.add_api_route(
        "/{entity_id}",
        delete_entity,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
        operation_id=f"delete_{spec.resource}",
    )
    return router


router = APIRouter()
for crud_spec in CRUD_SPECS:
    router.include_router(build_crud_router(crud_spec))
