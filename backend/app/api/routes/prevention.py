from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_db, require_write_access
from app.models.prevention import PreventionReport
from app.schemas.prevention import PreventionRequest
from app.services.prevention import assess

router = APIRouter(prefix="/prevention", tags=["比赛版体检规划"])
DB = Annotated[Session, Depends(get_db)]
Caller = Annotated[Principal, Depends(require_write_access)]


def _visible_reports(statement, principal: Principal):
    """参赛报告归属过滤：管理员与显式开发模式可见全部，其余只看自己创建的报告。"""

    if not principal.authenticated or principal.is_admin:
        return statement
    # 归属为空的报告创建于 T01 之前，无法判定所有者，只对管理员开放。
    return statement.where(PreventionReport.owner_account_id == principal.account_id)


@router.post("/assess")
def assessment(body: PreventionRequest, principal: Caller):
    return assess(body)


@router.post("/reports", status_code=201)
def save_report(body: PreventionRequest, db: DB, principal: Caller):
    # Never trust risk numbers or recommendation text supplied by the browser.
    row = PreventionReport(
        label=body.label, payload=assess(body), owner_account_id=principal.account_id
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "created_at": row.created_at, **row.payload}


@router.get("/reports")
def list_reports(db: DB, principal: Caller):
    rows = db.scalars(
        _visible_reports(select(PreventionReport), principal)
        .order_by(PreventionReport.created_at.desc(), PreventionReport.id.desc())
        .limit(100)
    ).all()
    return [{"id": r.id, "label": r.label, "created_at": r.created_at,
             "source": r.payload["input"]["source"]} for r in rows]


@router.get("/reports/{report_id}")
def get_report(report_id: str, db: DB, principal: Caller):
    row = db.scalar(_visible_reports(select(PreventionReport), principal).where(
        PreventionReport.id == report_id))
    if row is None:
        raise HTTPException(404, "报告不存在")
    return {"id": row.id, "created_at": row.created_at, **row.payload}
