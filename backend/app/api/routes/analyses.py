"""T04/T05：分析运行与跨系统候选汇总接口。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    Principal,
    ensure_patient_access,
    get_current_principal,
    get_db,
    require_write_access,
)
from app.models import AnalysisRun, Patient
from app.services.analysis.finding_map import load_finding_map
from app.services.analysis.runner import AnalysisRunner, input_fingerprint, missing_information

router = APIRouter(prefix="/analyses", tags=["analyses"])


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(min_length=1, max_length=36)
    as_of_date: date
    request_id: str | None = Field(default=None, min_length=1, max_length=80)


def serialize_run(db: Session, run: AnalysisRun) -> dict:
    patient = db.get(Patient, run.patient_id)
    stale = (
        patient is not None
        and input_fingerprint(db, patient, run.as_of_date) != run.input_fingerprint
    )
    return {
        "run_id": run.id,
        "patient_id": run.patient_id,
        "as_of_date": run.as_of_date,
        "status": run.status.value,
        "created_at": run.created_at,
        "is_demo": run.is_demo,
        "input_version": run.input_version,
        "input_fingerprint": run.input_fingerprint,
        "provider_version": run.provider_version,
        "finding_map_version": run.finding_map_version,
        "rule_set_versions": run.rule_set_versions or [],
        "findings": run.findings or [],
        "candidates": run.candidates or [],
        "summary": run.summary or {},
        "notes": run.notes or [],
        "error_message": run.error_message,
        # 资料变化后旧结果过期，但仍可按原版本回看。
        "stale": bool(stale),
        "stale_reason": "已确认资料在该决策日期之后发生变化，请重新分析" if stale else None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def run_analysis(
    payload: AnalysisRequest,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """执行一次分析：固定决策日期与输入版本，调用规则引擎汇总跨系统候选。"""

    patient = ensure_patient_access(db, principal, payload.patient_id)
    if payload.as_of_date > date.today():
        raise HTTPException(status_code=422, detail="决策日期不能晚于今天")
    try:
        run = AnalysisRunner(db).run(
            patient=patient,
            as_of_date=payload.as_of_date,
            request_id=payload.request_id,
            actor_account_id=principal.account_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_run(db, run)


@router.get("")
def list_analyses(
    patient_id: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    ensure_patient_access(db, principal, patient_id)
    runs = db.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.patient_id == patient_id)
        .order_by(AnalysisRun.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "run_id": run.id,
            "as_of_date": run.as_of_date,
            "created_at": run.created_at,
            "status": run.status.value,
            "summary": run.summary or {},
            "stale": input_fingerprint(db, db.get(Patient, run.patient_id), run.as_of_date)
            != run.input_fingerprint,
        }
        for run in runs
    ]


@router.get("/finding-map")
def finding_map(
    principal: Principal = Depends(get_current_principal),  # noqa: B008
):
    """发现→候选检查项目的工程映射（只读，供前端展示依据与待审核状态）。"""

    mapping = load_finding_map()
    return {
        "version": mapping.version,
        "source": mapping.source,
        "reviewed": False,
        "entries": [
            {
                "finding_code": rule.finding_code,
                "name": rule.name,
                "system": rule.system,
                "severity": rule.severity,
                "metric_codes": list(rule.metric_codes),
                "directions": list(rule.directions),
                "lesion_keywords": list(rule.lesion_keywords),
                "exam_codes": list(rule.exam_codes),
                "relation_type": rule.relation_type,
                "note": rule.note,
            }
            for rule in mapping.rules
        ],
    }


@router.get("/{run_id}")
def get_analysis(
    run_id: str,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="分析结果不存在")
    patient = ensure_patient_access(db, principal, run.patient_id)
    payload = serialize_run(db, run)
    payload["missing_information"] = missing_information(db, patient, run.as_of_date)
    return payload
