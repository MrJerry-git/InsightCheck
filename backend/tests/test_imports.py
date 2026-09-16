from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.importing.contracts import (
    EncounterRow,
    ImportRequest,
    ObservationRow,
    PatientRow,
    validate_bundle,
)
from app.importing.synthea import csv_text
from app.models import (
    HealthCheck,
    ImportBatch,
    ImportedRecord,
    LabMetric,
    MetricDictionary,
    Patient,
)
from app.models.enums import MetricStatus
from app.services.import_service import ImportConflictError, ImportService


def bundle() -> ImportRequest:
    return ImportRequest(
        source_version="a" * 64,
        patients_csv=csv_text(
            PatientRow,
            [
                {"source_id": "p1", "birth_date": "1980-01-01", "gender": "female"},
            ],
        ),
        encounters_csv=csv_text(
            EncounterRow,
            [
                {
                    "source_id": "e1",
                    "patient_source_id": "p1",
                    "event_time": "2020-01-01T10:00:00Z",
                    "encounter_type": "wellness",
                },
            ],
        ),
        observations_csv=csv_text(
            ObservationRow,
            [
                {
                    "source_id": "o1",
                    "patient_source_id": "p1",
                    "encounter_source_id": "e1",
                    "event_time": "2020-01-01T10:00:00Z",
                    "code": "29463-7",
                    "original_name": "Body Weight",
                    "original_value": "65.2",
                    "original_unit": "kg",
                },
            ],
        ),
    )


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_import_is_idempotent_and_preserves_source_without_identity(db_session):
    service = ImportService(db_session)
    first = service.run(bundle())
    second = service.run(bundle())
    assert first["batch_id"] == second["batch_id"]
    assert first["created"] == {"patients": 1, "encounters": 1, "observations": 1}
    assert second["created"] == dict.fromkeys(first["created"], 0)
    assert second["reused"] == first["created"]
    assert count(db_session, ImportedRecord) == 3
    assert count(db_session, ImportBatch) == 1
    assert db_session.scalar(select(HealthCheck)).is_demo
    metric = db_session.scalar(select(LabMetric))
    assert metric.status == MetricStatus.UNKNOWN
    assert metric.original_value == "65.2"
    assert metric.reference_min is None and metric.reference_max is None
    record = db_session.get(ImportedRecord, metric.id)
    assert record.payload["event_time"] == "2020-01-01T10:00:00Z"
    assert "SSN" not in str(record.payload)


@pytest.mark.parametrize(
    ("field", "old", "new"),
    [
        ("observations_csv", "kg", "lb"),
        ("observations_csv", "65.2", "NaN"),
        ("observations_csv", "65.2", "inf"),
        ("observations_csv", "o1,p1,e1", "o1,p2,e1"),
        ("observations_csv", "2020-01-01", "2019-01-01"),
        ("encounters_csv", "wellness", "inpatient"),
        ("encounters_csv", "2020-01-01", "1970-01-01"),
        ("encounters_csv", "10:00:00Z", "10:00:00"),
    ],
)
def test_invalid_bundle_returns_row_errors_without_writes(db_session, field, old, new):
    request = bundle()
    bad = request.model_copy(update={field: getattr(request, field).replace(old, new)})
    report, _ = validate_bundle(bad)
    assert not report.valid
    assert report.issues[0].row == 2
    assert ImportService(db_session).run(bad)["status"] == "invalid"
    assert count(db_session, Patient) == count(db_session, ImportBatch) == 0


def test_changed_source_does_not_overwrite_existing_entities(db_session):
    service = ImportService(db_session)
    request = bundle()
    service.run(request)
    changed = request.model_copy(
        update={
            "observations_csv": request.observations_csv.replace("65.2", "66.2"),
        }
    )
    with pytest.raises(ImportConflictError):
        service.run(changed)
    assert db_session.scalar(select(LabMetric.value)) == 65.2
    assert count(db_session, ImportBatch) == 1


def test_replay_detects_domain_edits(db_session):
    service = ImportService(db_session)
    service.run(bundle())
    db_session.scalar(select(Patient)).birth_date = date(1990, 1, 1)
    db_session.commit()
    with pytest.raises(ImportConflictError, match="modified"):
        service.run(bundle())


def test_duplicate_and_extra_identity_columns_are_rejected():
    request = bundle()
    duplicate = request.model_copy(
        update={
            "patients_csv": request.patients_csv + request.patients_csv.splitlines()[1] + "\n",
        }
    )
    assert not validate_bundle(duplicate)[0].valid
    identity = request.model_copy(
        update={
            "patients_csv": request.patients_csv.replace("gender\n", "gender,SSN\n"),
        }
    )
    assert validate_bundle(identity)[0].issues[0].field == "header"


def test_api_validates_without_writes_and_rejects_real_source(test_app, db_session):
    with TestClient(test_app) as client:
        data = bundle().model_dump()
        assert client.post("/api/v1/imports/validate", json=data).json()["valid"]
        assert count(db_session, ImportBatch) == 0
        assert client.post("/api/v1/imports", json=data).status_code == 200
        data["source_kind"] = "partner_observational"
        assert client.post("/api/v1/imports", json=data).status_code == 422


def test_runtime_failure_rolls_back_the_entire_batch(db_session, monkeypatch):
    service = ImportService(db_session)
    original = service._values

    def fail_on_observation(request, table, row):
        if table == "observations":
            raise RuntimeError("simulated storage failure")
        return original(request, table, row)

    monkeypatch.setattr(service, "_values", fail_on_observation)
    with pytest.raises(RuntimeError, match="storage failure"):
        service.run(bundle())
    for model in (Patient, HealthCheck, LabMetric, ImportBatch, ImportedRecord, MetricDictionary):
        assert count(db_session, model) == 0


def test_history_preserves_event_time_and_unknown_availability(test_app):
    with TestClient(test_app) as client:
        assert client.post("/api/v1/imports", json=bundle().model_dump()).status_code == 200
        patient = client.get("/api/v1/imports/patients").json()[0]
        response = client.get(f"/api/v1/imports/patients/{patient['id']}/timeline")
        assert response.status_code == 200
        history = response.json()
        assert history["source_kind"] == "synthetic"
        observation = history["checks"][0]["observations"][0]
        assert observation["value"] == 65.2
        assert observation["event_time"] == "2020-01-01T10:00:00Z"
        assert observation["available_at"] is None
        assert client.get("/api/v1/imports/patients/missing/timeline").status_code == 404
        data = bundle().model_dump()
        data["observations_csv"] = data["observations_csv"].replace("kg", "lb")
        assert client.post("/api/v1/imports", json=data).status_code == 422
