from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HealthCheck, ImportBatch, ImportedRecord, LabMetric, Patient


def imported_patient_history(session: Session, patient_id: str, limit: int) -> dict | None:
    patient = session.get(Patient, patient_id)
    source = session.get(ImportedRecord, patient_id)
    if patient is None or source is None or source.entity_type != "patients":
        return None
    batch = session.get(ImportBatch, source.batch_id)
    checks = session.scalars(
        select(HealthCheck)
        .where(HealthCheck.patient_id == patient_id)
        .order_by(HealthCheck.check_date.desc(), HealthCheck.id)
        .limit(limit + 1)
    ).all()
    truncated = len(checks) > limit
    checks = checks[:limit]
    results = []
    for check in checks:
        check_source = session.get(ImportedRecord, check.id)
        observations = session.execute(
            select(LabMetric, ImportedRecord)
            .join(ImportedRecord, LabMetric.id == ImportedRecord.id)
            .where(LabMetric.health_check_id == check.id)
            .order_by(LabMetric.metric_code, LabMetric.id)
        ).all()
        results.append(
            {
                "id": check.id,
                "check_date": check.check_date.isoformat(),
                "event_time": check_source.payload["event_time"] if check_source else None,
                "encounter_type": "wellness" if check_source else "unknown",
                "observations": [
                    {
                        "id": metric.id,
                        "code": metric.metric_code,
                        "name": metric.canonical_name,
                        "value": metric.value,
                        "unit": metric.standard_unit,
                        "original_value": metric.original_value,
                        "original_unit": metric.original_unit,
                        "event_time": record.payload["event_time"],
                        "available_at": None,
                        "status": metric.status.value,
                    }
                    for metric, record in observations
                ],
            }
        )
    return {
        "patient_id": patient.id,
        "anonymous_code": patient.anonymous_code,
        "source_kind": batch.source_kind,
        "source_dataset": batch.source_dataset,
        "source_version": batch.source_version,
        "checks": results,
        "truncated": truncated,
        "availability_warning": (
            "Source has no available_at; history is not a leakage-safe model input"
        ),
    }
