from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import AIReport, HealthCheck, Patient, Recommendation


def setup_case(client):
    response = client.post("/api/v1/workflow/demo")
    assert response.status_code == 200
    return response.json()["patient_id"]


def payload(patient_id, **kwargs):
    return {
        "request_id": str(uuid4()),
        "patient_id": patient_id,
        "as_of_date": "2025-12-31",
        "tier": "standard",
        **kwargs,
    }


def test_end_to_end_models_save_replay_snapshot(test_app, db_session):
    pytest.importorskip("lightgbm")
    with TestClient(test_app) as client:
        patient_id = setup_case(client)
        p = payload(patient_id)
        response = client.post("/api/v1/workflow/plans", json=p)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["risk"]["probability"] is not None
        assert all(item["score"] is not None for item in result["items"])
        assert all(item["rule_status"] == "NOT_CONFIGURED" for item in result["items"])
        assert client.post("/api/v1/workflow/plans", json=p).json() == result
        assert db_session.scalar(select(func.count()).select_from(Recommendation)) == 1
        db_session.get(Patient, patient_id).anonymous_code = "CHANGED"
        db_session.commit()
        assert client.get(f"/api/v1/workflow/plans/{result['id']}").json() == result
        exported = client.get(f"/api/v1/workflow/plans/{result['id']}/export")
        assert exported.json() == result
        assert "attachment;" in exported.headers["content-disposition"]
        conflict = client.post("/api/v1/workflow/plans", json={**p, "tier": "deep"})
        assert conflict.status_code == 409
        answer = client.post(
            f"/api/v1/workflow/plans/{result['id']}/explain", json={"text": "费用是多少"}
        ).json()
        assert "无法计算" in answer["answer"]


def test_real_records_never_call_synthetic_models(test_app, db_session, monkeypatch):
    with TestClient(test_app) as client:
        patient_id = setup_case(client)
        check = db_session.scalar(select(HealthCheck).where(HealthCheck.patient_id == patient_id))
        check.is_demo = False
        db_session.commit()

        def forbidden(*args):
            raise AssertionError("synthetic inference called for non-demo records")

        monkeypatch.setattr("app.api.routes.workflow.predict", forbidden)
        result = client.post("/api/v1/workflow/plans", json=payload(patient_id)).json()
        assert result["risk"]["probability"] is None
        assert all(i["group"] == "需复核" for i in result["items"])


def test_cutoff_empty_future_and_wrong_patient(test_app, monkeypatch):
    monkeypatch.setattr("app.api.routes.workflow.predict", lambda *a: (0.5, {}))
    with TestClient(test_app) as client:
        patient_id = setup_case(client)
        history = client.get(f"/api/v1/workflow/patients/{patient_id}?as_of_date=2023-12-31").json()
        assert len(history["checks"]) == 2
        assert len(history["tracks"][0]["observations"]) == 2
        assert (
            client.post(
                "/api/v1/workflow/plans", json=payload(patient_id, as_of_date="2000-01-01")
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/workflow/plans", json=payload(patient_id, as_of_date="2999-01-01")
            ).status_code
            == 422
        )
        assert client.post("/api/v1/workflow/plans", json=payload("unknown")).status_code == 404


def test_save_failure_rolls_back_entire_plan(test_app, db_session, monkeypatch):
    monkeypatch.setattr("app.api.routes.workflow.predict", lambda *a: (0.5, {}))
    with TestClient(test_app, raise_server_exceptions=False) as client:
        patient_id = setup_case(client)

        def fail():
            raise RuntimeError("simulated database failure")

        with monkeypatch.context() as patch:
            patch.setattr(db_session, "commit", fail)
            assert (
                client.post("/api/v1/workflow/plans", json=payload(patient_id)).status_code == 500
            )
        assert db_session.scalar(select(func.count()).select_from(Recommendation)) == 0
        assert db_session.scalar(select(func.count()).select_from(AIReport)) == 0


def test_manual_record_validation_and_persistence(test_app, db_session):
    with TestClient(test_app) as client:
        patient_id = setup_case(client)
        p = {
            "patient_id": patient_id,
            "check_date": str(date.today()),
            "metrics": [{"code": "ALT", "value": 31.2}],
        }
        response = client.post("/api/v1/workflow/records", json=p)
        assert response.status_code == 200
        assert db_session.get(HealthCheck, response.json()["id"]).is_demo is False
        assert (
            client.post(
                "/api/v1/workflow/records", json={**p, "metrics": p["metrics"] * 2}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/workflow/records", json={**p, "check_date": "1900-01-01"}
            ).status_code
            == 422
        )
