"""T09/T10：报告导出与依据问答接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import (
    Principal,
    ensure_patient_access,
    get_current_principal,
    get_db,
    require_write_access,
)
from app.models import Plan, ReportExport
from app.services.qa import QaError, QaService
from app.services.reporting.reports import ReportError, ReportService

router = APIRouter(tags=["reports"])


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(min_length=1, max_length=36)
    question: str = Field(min_length=1, max_length=1000)
    plan_id: str | None = Field(default=None, max_length=36)
    request_id: str | None = Field(default=None, min_length=1, max_length=80)


def plan_or_404(db: Session, principal: Principal, plan_id: str) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="方案不存在")
    ensure_patient_access(db, principal, plan.patient_id)
    return plan


def translate(exc: ReportError | QaError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/reports/{plan_id}")
def report_document(
    plan_id: str,
    revision_no: int | None = Query(default=None, ge=1),  # noqa: B008
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """报告内容（与所选修订一致），包含来源、规则版本与模型模式。"""

    plan = plan_or_404(db, principal, plan_id)
    try:
        return ReportService(db).document(plan, revision_no=revision_no)
    except ReportError as exc:
        raise translate(exc) from exc


@router.get("/reports/{plan_id}/evidence")
def report_evidence(
    plan_id: str,
    revision_no: int | None = Query(default=None, ge=1),  # noqa: B008
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """JSON 证据导出：记录引用、规则来源与价格来源。"""

    plan = plan_or_404(db, principal, plan_id)
    try:
        document = ReportService(db).document(plan, revision_no=revision_no)
    except ReportError as exc:
        raise translate(exc) from exc
    return {
        "plan_id": plan.id,
        "revision_no": document["revision_no"],
        "price_catalog_version": document["price_catalog_version"],
        "rule_set_versions": document["rule_set_versions"],
        "model_status": document["analysis"]["model_status"],
        "evidence": document["evidence"],
    }


@router.get("/reports/{plan_id}/pdf")
def report_pdf(
    plan_id: str,
    revision_no: int | None = Query(default=None, ge=1),  # noqa: B008
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """中文 PDF 下载；内容来自已保存版本，不做二次计算。"""

    plan = plan_or_404(db, principal, plan_id)
    service = ReportService(db)
    try:
        document = service.document(plan, revision_no=revision_no)
    except ReportError as exc:
        raise translate(exc) from exc
    payload = service.render_pdf(document)
    export = ReportExport(
        plan_id=plan.id,
        revision_no=document["revision_no"],
        report_format="pdf",
        content_sha256=service.digest(payload),
        size_bytes=len(payload),
        created_by_account_id=principal.account_id,
    )
    db.add(export)
    db.commit()
    filename = f"InsightCheck-plan-{plan.id}-r{document['revision_no']}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/qa/ask")
def ask(
    payload: AskRequest,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """基于当前档案与方案快照回答；引用可追溯，问答不会修改方案。"""

    patient = ensure_patient_access(db, principal, payload.patient_id)
    plan = None
    if payload.plan_id:
        plan = plan_or_404(db, principal, payload.plan_id)
        if plan.patient_id != patient.id:
            raise HTTPException(status_code=409, detail="方案不属于该档案")
    try:
        return QaService(db).ask(
            patient=patient,
            question=payload.question,
            plan=plan,
            request_id=payload.request_id,
            actor_account_id=principal.account_id,
        )
    except QaError as exc:
        raise translate(exc) from exc


@router.get("/qa/history")
def qa_history(
    patient_id: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    ensure_patient_access(db, principal, patient_id)
    from app.models import QaRecord

    records = (
        db.query(QaRecord)
        .filter(QaRecord.patient_id == patient_id)
        .order_by(QaRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    return [QaService(db)._serialize(record) for record in records]  # noqa: SLF001
