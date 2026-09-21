"""T03：文件导入任务的上传、逐字段校对、重复识别与事务性入库。"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    HealthCheck,
    ImportTask,
    LabMetric,
    MetricDictionary,
    Patient,
    RecordRevision,
)
from app.models.enums import AccountRole, Gender, ImportTaskStatus, ValueType
from app.services.auth_service import AuthService
from app.services.import_tasks import ImportTaskService

DOCTOR_PASSWORD = "Doctor-Pass-2026!"
HEADER = "date,metric_code,original_name,value,unit,reference_min,reference_max\n"


def make_account(db, username):
    return AuthService(db, iterations=10_000).create_account(
        username=username, password=DOCTOR_PASSWORD, display_name=username,
        role=AccountRole.DOCTOR,
    )


def login(client, username):
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": DOCTOR_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def seed_dictionary(db, code="ALT", value_type=ValueType.NUMERIC, unit="U/L"):
    definition = MetricDictionary(
        metric_code=code,
        canonical_name="丙氨酸氨基转移酶",
        aliases=[],
        standard_unit=unit,
        category="肝功能",
        value_type=value_type,
        unit_conversions={},
        source="测试来源",
        version="v1",
    )
    db.add(definition)
    db.commit()
    return definition


def create_patient(client, headers, code="P-IMPORT-001", birth_date=None):
    payload = {"anonymous_code": code, "gender": "female"}
    if birth_date:
        payload["birth_date"] = birth_date
    response = client.post("/api/v1/patients", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, headers, patient_id, content: str, filename="report.csv", **form):
    response = client.post(
        "/api/v1/imports/tasks",
        data={"patient_id": patient_id, **form},
        files={"file": (filename, content.encode("utf-8"), "text/csv")},
        headers=headers,
    )
    return response


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.import_tasks.get_settings",
        lambda: type("S", (), {"import_task_storage_dir": str(tmp_path / "tasks")})(),
    )


def test_upload_produces_preview_without_writing_records(test_app, db_session):
    make_account(db_session, "doctor-a")
    seed_dictionary(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        content = HEADER + "2026-01-05,ALT,丙氨酸氨基转移酶,35,U/L,0,40\n"
        response = upload(client, headers, patient_id, content)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "preview_ready"
        assert body["rows"][0]["include"] is True
        assert body["rows"][0]["source_ref"] == "第 2 行"
        # 上传只产生预览：业务表里还没有检查记录。
        assert db_session.scalars(select(HealthCheck)).all() == []
        assert db_session.scalars(select(LabMetric)).all() == []


def test_row_level_errors_and_blocking_confirmation(test_app, db_session):
    make_account(db_session, "doctor-a")
    seed_dictionary(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers, birth_date="1990-01-01")
        content = HEADER + (
            "2026-13-40,ALT,丙氨酸氨基转移酶,35,U/L,0,40\n"
            "2026-01-05,ALT,丙氨酸氨基转移酶,abc,U/L,0,40\n"
            "2026-01-06,ALT,丙氨酸氨基转移酶,35,U/L,60,40\n"
            "2026-01-07,UNKNOWN_CODE,未知指标,1.2,,,\n"
        )
        body = upload(client, headers, patient_id, content).json()
        codes = [[item["code"] for item in row["issues"]] for row in body["rows"]]
        assert "invalid_date" in codes[0]
        assert "invalid_value" in codes[1]
        assert "reference_range_invalid" in codes[2]
        assert "unmapped_metric" in codes[3] and "missing_unit" in codes[3]
        assert len(body["blocking_row_ids"]) == 3

        blocked = client.post(
            f"/api/v1/imports/tasks/{body['task_id']}/confirm", json={}, headers=headers
        )
        assert blocked.status_code == 422
        assert "必须修正" in blocked.json()["detail"]["message"]

        # 只勾选可入库的未映射行：保留原文，标记待映射，不静默丢弃。
        fixed = client.patch(
            f"/api/v1/imports/tasks/{body['task_id']}",
            json={
                "rows": [
                    {"row_id": row["row_id"], "include": False}
                    for row in body["rows"]
                    if row["row_id"] != body["rows"][3]["row_id"]
                ]
            },
            headers=headers,
        )
        assert fixed.status_code == 200, fixed.text
        assert fixed.json()["blocking_row_ids"] == []
        confirmed = client.post(
            f"/api/v1/imports/tasks/{body['task_id']}/confirm", json={}, headers=headers
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["result"]["created_metric_count"] == 1
        metric = db_session.scalar(select(LabMetric))
        assert metric.metric_code == "UNMAPPED"
        assert metric.original_name == "未知指标"
        assert metric.source_ref.startswith(f"import_task:{body['task_id']}")


def test_proofread_then_confirm_writes_records_with_revisions(test_app, db_session):
    make_account(db_session, "doctor-a")
    seed_dictionary(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        content = HEADER + "2026-01-05,ALT,丙氨酸氨基转移酶,3.5,U/L,0,40\n"
        body = upload(client, headers, patient_id, content).json()
        assert "missing_unit" not in [item["code"] for item in body["rows"][0]["issues"]]

        # 校对：把数值改为 35，并补上参考区间。
        fixed = client.patch(
            f"/api/v1/imports/tasks/{body['task_id']}",
            json={
                "rows": [
                    {
                        "row_id": body["rows"][0]["row_id"],
                        "original_value": "35",
                        "reference_min": 0,
                        "reference_max": 40,
                    }
                ]
            },
            headers=headers,
        )
        assert fixed.status_code == 200, fixed.text
        assert fixed.json()["rows"][0]["value"] == 35

        confirmed = client.post(
            f"/api/v1/imports/tasks/{body['task_id']}/confirm", json={}, headers=headers
        )
        assert confirmed.status_code == 200, confirmed.text
        summary = confirmed.json()["result"]
        assert summary["created_metric_count"] == 1

        metric = db_session.scalar(select(LabMetric))
        assert metric.value == 35
        assert metric.standard_unit == "U/L"
        assert metric.source_kind == "import"
        check = db_session.get(HealthCheck, metric.health_check_id)
        assert check.check_date == date(2026, 1, 5)
        assert check.source_kind == "import"
        revisions = [
            item
            for item in db_session.scalars(select(RecordRevision)).all()
            if item.entity_type in {"health_check", "lab_metric"}
        ]
        assert {item.source_kind for item in revisions} == {"import"}
        assert len(revisions) == 2
        # 确认后临时文件被清理。
        task = db_session.get(ImportTask, body["task_id"])
        assert task.status is ImportTaskStatus.CONFIRMED
        assert task.temporary_path is None

        # 重复确认是幂等的，不会重复写入。
        again = client.post(
            f"/api/v1/imports/tasks/{body['task_id']}/confirm", json={}, headers=headers
        )
        assert again.status_code == 200
        assert len(db_session.scalars(select(LabMetric)).all()) == 1


def test_same_file_and_same_day_conflicts_require_explicit_decision(test_app, db_session):
    make_account(db_session, "doctor-a")
    seed_dictionary(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        content = HEADER + "2026-01-05,ALT,丙氨酸氨基转移酶,35,U/L,0,40\n"
        first = upload(client, headers, patient_id, content).json()
        assert (
            client.post(
                f"/api/v1/imports/tasks/{first['task_id']}/confirm", json={}, headers=headers
            ).status_code
            == 200
        )

        # 同一文件再次上传：识别为重复任务，需要显式允许。
        second = upload(client, headers, patient_id, content).json()
        assert second["duplicate_of_task_id"] == first["task_id"]
        assert second["rows"][0]["duplicate_of_record_id"] is not None
        denied = client.post(
            f"/api/v1/imports/tasks/{second['task_id']}/confirm", json={}, headers=headers
        )
        assert denied.status_code == 409
        merged = client.post(
            f"/api/v1/imports/tasks/{second['task_id']}/confirm",
            json={"allow_duplicate": True, "merge_same_day": True},
            headers=headers,
        )
        assert merged.status_code == 200, merged.text
        # 同日同指标不静默覆盖：跳过重复行并如实返回。
        assert merged.json()["result"]["created_metric_count"] == 0
        assert merged.json()["result"]["skipped_row_ids"]
        assert len(db_session.scalars(select(LabMetric)).all()) == 1


def test_unsupported_type_size_and_missing_file(test_app, db_session):
    make_account(db_session, "doctor-a")
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        unsupported = client.post(
            "/api/v1/imports/tasks",
            data={"patient_id": patient_id},
            files={"file": ("report.xlsx", b"binary", "application/vnd.ms-excel")},
            headers=headers,
        )
        assert unsupported.status_code == 415
        oversized = upload(
            client, headers, patient_id, "x" * (8 * 1024 * 1024 + 1), filename="big.csv"
        )
        assert oversized.status_code == 413


def test_tasks_are_scoped_to_patient_owner(test_app, db_session):
    make_account(db_session, "doctor-a")
    make_account(db_session, "doctor-b")
    seed_dictionary(db_session)
    with TestClient(test_app) as client:
        headers_a = login(client, "doctor-a")
        headers_b = login(client, "doctor-b")
        patient_id = create_patient(client, headers_a)
        body = upload(
            client, headers_a, patient_id, HEADER + "2026-01-05,ALT,ALT,35,U/L,0,40\n"
        ).json()
        other = client.get(f"/api/v1/imports/tasks/{body['task_id']}", headers=headers_b)
        assert other.status_code == 403
        assert client.get("/api/v1/imports/tasks", headers=headers_b).json() == []
        assert (
            upload(
                client, headers_b, patient_id, HEADER + "2026-01-05,ALT,ALT,35,U/L,0,40\n"
            ).status_code
            == 403
        )


def test_retry_and_cancel_lifecycle(test_app, db_session):
    make_account(db_session, "doctor-a")
    seed_dictionary(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        content = HEADER + "2026-01-05,ALT,ALT,35,U/L,0,40\n"
        body = upload(client, headers, patient_id, content).json()
        retried = client.post(
            f"/api/v1/imports/tasks/{body['task_id']}/retry", headers=headers
        )
        assert retried.status_code == 200
        assert retried.json()["attempts"] == 2
        assert retried.json()["status"] == "preview_ready"

        cancelled = client.delete(
            f"/api/v1/imports/tasks/{body['task_id']}", headers=headers
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert db_session.scalars(select(LabMetric)).all() == []


def test_request_id_is_idempotent(test_app, db_session):
    make_account(db_session, "doctor-a")
    seed_dictionary(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        content = HEADER + "2026-01-05,ALT,ALT,35,U/L,0,40\n"
        first = upload(client, headers, patient_id, content, request_id="op-1")
        second = upload(client, headers, patient_id, content, request_id="op-1")
        assert first.json()["task_id"] == second.json()["task_id"]
        conflict = upload(
            client, headers, patient_id, HEADER + "2026-01-06,ALT,ALT,35,U/L,0,40\n",
            request_id="op-1",
        )
        assert conflict.status_code == 409


def test_model_parser_reports_unavailable_service(test_app, db_session, monkeypatch):
    """模型不可用时任务进入 failed 并说明原因，不产生假的提取结果。"""

    make_account(db_session, "doctor-a")
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        import httpx

        def unavailable(*_args, **_kwargs):
            raise httpx.ConnectError("no ollama")

        monkeypatch.setattr("app.services.smart_import.extract", unavailable)
        response = client.post(
            "/api/v1/imports/tasks",
            data={"patient_id": patient_id},
            files={"file": ("report.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            headers=headers,
        )
        assert response.status_code == 503
        task = db_session.scalar(select(ImportTask))
        assert task.status is ImportTaskStatus.FAILED
        assert "模型服务不可用" in (task.error_message or "")


def test_service_confirm_is_transactional(db_session):
    """入库中途失败时不留下半成品：整体回滚。"""

    make_account(db_session, "doctor-a")
    seed_dictionary(db_session)
    patient = Patient(anonymous_code="P-TX-001", gender=Gender.UNKNOWN)
    db_session.add(patient)
    db_session.commit()

    service = ImportTaskService(db_session)
    task = service.create_task(
        patient=patient,
        filename="report.csv",
        content_type="text/csv",
        raw=(HEADER + "2026-01-05,ALT,ALT,35,U/L,0,40\n").encode(),
    )
    assert task.status is ImportTaskStatus.PREVIEW_READY

    original = LabMetric.__init__

    def exploding(self, *args, **kwargs):
        raise RuntimeError("boom")

    LabMetric.__init__ = exploding
    try:
        with pytest.raises(RuntimeError):
            service.confirm(task)
    finally:
        LabMetric.__init__ = original
    assert db_session.scalars(select(HealthCheck)).all() == []
    assert db_session.scalars(select(LabMetric)).all() == []
    assert db_session.get(ImportTask, task.id).status is ImportTaskStatus.PREVIEW_READY
