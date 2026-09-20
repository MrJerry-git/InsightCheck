from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.models.prevention import PreventionReport
from app.schemas.prevention import PreventionRequest
from app.services.prevention import assess

router = APIRouter(prefix="/prevention", tags=["比赛版体检规划"])
DB = Annotated[Session, Depends(get_db)]


@router.post("/assess")
def assessment(body: PreventionRequest):
    return assess(body)


@router.post("/reports", status_code=201)
def save_report(body: PreventionRequest, db: DB):
    # Never trust risk numbers or recommendation text supplied by the browser.
    row = PreventionReport(label=body.label, payload=assess(body))
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "created_at": row.created_at, **row.payload}


@router.get("/reports")
def list_reports(db: DB):
    rows = db.scalars(select(PreventionReport).order_by(
        PreventionReport.created_at.desc(), PreventionReport.id.desc()).limit(100)).all()
    return [{"id": r.id, "label": r.label, "created_at": r.created_at,
             "source": r.payload["input"]["source"]} for r in rows]


@router.get("/reports/{report_id}")
def get_report(report_id: str, db: DB):
    row = db.get(PreventionReport, report_id)
    if row is None:
        raise HTTPException(404, "报告不存在")
    return {"id": row.id, "created_at": row.created_at, **row.payload}
