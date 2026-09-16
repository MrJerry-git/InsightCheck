from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.importing.contracts import ImportRequest, ValidationReport, validate_bundle
from app.models import ImportBatch, ImportedRecord, Patient
from app.services.import_history_service import imported_patient_history
from app.services.import_service import ImportConflictError, ImportService

router = APIRouter(prefix="/imports", tags=["synthetic-imports"])


@router.get("/patients")
def list_imported_patients(
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),  # noqa: B008
) -> list[dict]:
    rows = db.execute(
        select(Patient, ImportBatch)
        .join(ImportedRecord, Patient.id == ImportedRecord.id)
        .join(ImportBatch, ImportedRecord.batch_id == ImportBatch.id)
        .order_by(Patient.anonymous_code)
        .limit(limit)
    ).all()
    return [
        {
            "id": patient.id,
            "anonymous_code": patient.anonymous_code,
            "source_kind": batch.source_kind,
            "source_version": batch.source_version,
        }
        for patient, batch in rows
    ]


@router.get("/patients/{patient_id}/timeline")
def get_imported_history(
    patient_id: str,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),  # noqa: B008
) -> dict:
    result = imported_patient_history(db, patient_id, limit)
    if result is None:
        raise HTTPException(status_code=404, detail="imported patient not found")
    return result


@router.post("/validate", response_model=ValidationReport)
def validate_import(payload: ImportRequest) -> ValidationReport:
    return validate_bundle(payload)[0]


@router.post("")
def import_bundle(payload: ImportRequest, db: Session = Depends(get_db)) -> dict:  # noqa: B008
    try:
        result = ImportService(db).run(payload)
    except ImportConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result["status"] == "invalid":
        raise HTTPException(status_code=422, detail=result["validation"])
    return result
