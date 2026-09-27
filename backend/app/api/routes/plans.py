"""T06/T07：三档方案、价格接入、编辑复算、审核与快照接口。"""

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
from app.models import AnalysisRun, Plan
from app.models.enums import PlanTier
from app.services.plans import PlanError, PlanService

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(min_length=1, max_length=36)
    analysis_run_id: str = Field(min_length=1, max_length=36)
    tiers: list[PlanTier] = Field(default_factory=list, max_length=3)
    budget_limit_cents: int | None = Field(default=None, ge=0)
    budget_currency: str | None = Field(default=None, max_length=8)
    institution: str | None = Field(default=None, max_length=200)
    region: str | None = Field(default=None, max_length=100)
    request_id: str | None = Field(default=None, min_length=1, max_length=80)


class PlanEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    add_exam_codes: list[str] = Field(default_factory=list, max_length=50)
    remove_exam_codes: list[str] = Field(default_factory=list, max_length=50)
    budget_limit_cents: int | None = Field(default=None, ge=0)
    budget_currency: str | None = Field(default=None, max_length=8)


def plan_or_404(db: Session, principal: Principal, plan_id: str) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="方案不存在")
    ensure_patient_access(db, principal, plan.patient_id)
    return plan


def translate(exc: PlanError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: PlanCreateRequest,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """基于一次分析运行生成三档方案；价格与预算全部来自服务端。"""

    patient = ensure_patient_access(db, principal, payload.patient_id)
    run = db.get(AnalysisRun, payload.analysis_run_id)
    if run is None or run.patient_id != patient.id:
        raise HTTPException(status_code=404, detail="分析结果不存在或不属于该档案")
    try:
        plan = PlanService(db).create(
            patient=patient,
            analysis_run=run,
            tiers=tuple(payload.tiers) or None,
            budget_limit_cents=payload.budget_limit_cents,
            budget_currency=payload.budget_currency,
            institution=payload.institution,
            region=payload.region,
            request_id=payload.request_id,
            actor_account_id=principal.account_id,
        )
    except PlanError as exc:
        raise translate(exc) from exc
    return PlanService(db).serialize(plan)


@router.get("")
def list_plans(
    patient_id: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    ensure_patient_access(db, principal, patient_id)
    plans = db.scalars(
        select(Plan)
        .where(Plan.patient_id == patient_id)
        .order_by(Plan.created_at.desc())
        .limit(limit)
    ).all()
    return [PlanService(db).serialize(plan, include_snapshot=False) for plan in plans]


@router.get("/{plan_id}")
def get_plan(
    plan_id: str,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    return PlanService(db).serialize(plan_or_404(db, principal, plan_id))


@router.patch("/{plan_id}")
def edit_plan(
    plan_id: str,
    payload: PlanEditRequest,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """增删项目触发后端复算：重新执行规则、重算费用并生成新修订。"""

    plan = plan_or_404(db, principal, plan_id)
    try:
        updated = PlanService(db).edit(
            plan,
            reason=payload.reason,
            add_exam_codes=payload.add_exam_codes,
            remove_exam_codes=payload.remove_exam_codes,
            budget_limit_cents=payload.budget_limit_cents,
            budget_currency=payload.budget_currency,
            actor_account_id=principal.account_id,
        )
    except PlanError as exc:
        raise translate(exc) from exc
    return PlanService(db).serialize(updated)


@router.post("/{plan_id}/submit-review")
def submit_review(
    plan_id: str,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    plan = plan_or_404(db, principal, plan_id)
    try:
        updated = PlanService(db).submit_review(plan, actor_account_id=principal.account_id)
    except PlanError as exc:
        raise translate(exc) from exc
    return PlanService(db).serialize(updated)


@router.post("/{plan_id}/confirm")
def confirm_plan(
    plan_id: str,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    plan = plan_or_404(db, principal, plan_id)
    try:
        updated = PlanService(db).confirm_plan(plan, actor_account_id=principal.account_id)
    except PlanError as exc:
        raise translate(exc) from exc
    return PlanService(db).serialize(updated)


def serialize_revision(revision) -> dict:
    return {
        "revision_no": revision.revision_no,
        "action": revision.action,
        "reason": revision.reason,
        "analysis_run_id": revision.analysis_run_id,
        "price_catalog_version": revision.price_catalog_version,
        "created_at": revision.created_at,
        "created_by_account_id": revision.created_by_account_id,
        "snapshot": revision.snapshot,
    }


@router.get("/{plan_id}/revisions")
def list_revisions(
    plan_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    plan = plan_or_404(db, principal, plan_id)
    return [
        {
            "revision_no": revision.revision_no,
            "action": revision.action,
            "reason": revision.reason,
            "price_catalog_version": revision.price_catalog_version,
            "created_at": revision.created_at,
        }
        for revision in PlanService(db).revisions(plan, limit=limit)
    ]


@router.get("/{plan_id}/revisions/{revision_no}")
def get_revision(
    plan_id: str,
    revision_no: int,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """只读回看历史修订：价格或规则调整不改变已保存快照。"""

    plan = plan_or_404(db, principal, plan_id)
    try:
        revision = PlanService(db).revision(plan, revision_no)
    except PlanError as exc:
        raise translate(exc) from exc
    return serialize_revision(revision)


@router.get("/{plan_id}/price-known")
def price_coverage(
    plan_id: str,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """价格覆盖情况：未知价格不参与总价，也不冒充完整预算。"""

    plan = plan_or_404(db, principal, plan_id)
    tiers = plan.current_snapshot.get("tiers_result", [])
    return {
        "price_catalog_version": plan.price_catalog_version,
        "as_of_date": plan.as_of_date.isoformat(),
        "tiers": [
            {
                "tier": tier["tier"],
                "cost_summary": tier["cost_summary"],
                "budget_status": tier["budget_status"],
                "budget_note": tier["budget_note"],
                "conflicts": tier.get("conflicts", []),
            }
            for tier in tiers
        ],
    }


@router.get("/{plan_id}/stale-check")
def stale_check(
    plan_id: str,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    plan = plan_or_404(db, principal, plan_id)
    payload = PlanService(db).serialize(plan, include_snapshot=False)
    return {
        "plan_id": plan.id,
        "stale": payload["stale"],
        "stale_reason": payload["stale_reason"],
        "revision_no": plan.revision_no,
    }

