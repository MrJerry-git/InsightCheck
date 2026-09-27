"""T02：多系统记录的持久化、值类型与修订历史。"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import LabMetric, MetricDictionary, RecordRevision
from app.models.enums import AccountRole, Gender, ValueType
from app.services.auth_service import AuthService

ADMIN_PASSWORD = "Admin-Pass-2026!"
DOCTOR_PASSWORD = "Doctor-Pass-2026!"


def make_account(db, username, role=AccountRole.DOCTOR):
    password = ADMIN_PASSWORD if role is AccountRole.ADMIN else DOCTOR_PASSWORD
    return AuthService(db, iterations=10_000).create_account(
        username=username, password=password, display_name=username, role=role
    )


def login(client, username, role=AccountRole.DOCTOR):
    password = ADMIN_PASSWORD if role is AccountRole.ADMIN else DOCTOR_PASSWORD
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def seed_dictionary(db, code="ALT", value_type=ValueType.NUMERIC):
    definition = MetricDictionary(
        metric_code=code,
        canonical_name="丙氨酸氨基转移酶",
        aliases=[],
        standard_unit="U/L",
        category="肝功能",
        value_type=value_type,
        unit_conversions={},
        source="测试来源",
        version="v1",
    )
    db.add(definition)
    db.commit()
    return definition


def create_patient(client, headers, code="P-T02-001"):
    response = client.post(
        "/api/v1/patients", json={"anonymous_code": code, "gender": "female"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_check(client, headers, patient_id, check_date="2026-01-05", source_ref="报告第 1 页"):
    response = client.post(
        "/api/v1/health-checks",
        json={
            "patient_id": patient_id,
            "check_date": check_date,
            "source_kind": "import",
            "source_ref": source_ref,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_numeric_metric_writes_revision_and_keeps_provenance(test_app, db_session):
    make_account(db_session, "doctor-a")
    seed_dictionary(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        check = create_check(client, headers, patient_id)
        assert check["source_kind"] == "import"
        assert check["source_ref"] == "报告第 1 页"
        assert check["revision_no"] == 1

        created = client.post(
            "/api/v1/lab-metrics",
            json={
                "health_check_id": check["id"],
                "metric_code": "ALT",
                "original_name": "ALT",
                "canonical_name": "丙氨酸氨基转移酶",
                "original_value": "35",
                "value": 35,
                "original_unit": "U/L",
                "standard_unit": "U/L",
                "normalization_status": "normalized",
                "normalization_version": "v1",
                "value_type": "numeric",
                "source_kind": "import",
                "source_ref": "报告第 1 页",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        metric = created.json()
        assert metric["value_type"] == "numeric"
        assert metric["revision_no"] == 1

        history = client.get(
            f"/api/v1/records/lab_metric/{metric['id']}/revisions", headers=headers
        )
        assert history.status_code == 200
        revisions = history.json()["revisions"]
        assert [item["revision_no"] for item in revisions] == [1]
        assert revisions[0]["action"] == "create"
        assert revisions[0]["source_kind"] == "import"
        assert revisions[0]["source_ref"] == "报告第 1 页"
        assert revisions[0]["after"]["value"] == 35


def test_update_records_before_and_after_values(test_app, db_session):
    make_account(db_session, "doctor-a")
    seed_dictionary(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        check = create_check(client, headers, patient_id)
        metric = client.post(
            "/api/v1/lab-metrics",
            json={
                "health_check_id": check["id"],
                "metric_code": "ALT",
                "original_name": "ALT",
                "canonical_name": "丙氨酸氨基转移酶",
                "original_value": "35",
                "value": 35,
                "normalization_status": "normalized",
                "normalization_version": "v1",
            },
            headers=headers,
        ).json()

        updated = client.patch(
            f"/api/v1/lab-metrics/{metric['id']}",
            json={"value": 48, "original_value": "48", "status": "high"},
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision_no"] == 2

        revisions = client.get(
            f"/api/v1/records/lab_metric/{metric['id']}/revisions", headers=headers
        ).json()["revisions"]
        assert [item["revision_no"] for item in revisions] == [2, 1]
        latest = revisions[0]
        assert latest["action"] == "update"
        # revision_no 属于版本管理字段，不列入业务变更字段。
        assert set(latest["changed_fields"]) == {"value", "original_value", "status"}
        assert latest["before"]["value"] == 35
        assert latest["after"]["value"] == 48

        # 档案维度也能回看到这条记录的历史。
        profile_history = client.get(
            f"/api/v1/profiles/{patient_id}/revisions?entity_type=lab_metric", headers=headers
        ).json()
        assert profile_history["count"] == 2


def test_delete_keeps_snapshot_and_is_traceable(test_app, db_session):
    make_account(db_session, "doctor-a")
    seed_dictionary(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        check = create_check(client, headers, patient_id)
        metric = client.post(
            "/api/v1/lab-metrics",
            json={
                "health_check_id": check["id"],
                "metric_code": "ALT",
                "original_name": "ALT",
                "canonical_name": "丙氨酸氨基转移酶",
                "original_value": "35",
                "value": 35,
                "normalization_status": "normalized",
                "normalization_version": "v1",
            },
            headers=headers,
        ).json()

        assert (
            client.delete(f"/api/v1/lab-metrics/{metric['id']}", headers=headers).status_code
            == 204
        )
        revisions = client.get(
            f"/api/v1/records/lab_metric/{metric['id']}/revisions", headers=headers
        ).json()["revisions"]
        assert [item["action"] for item in revisions] == ["delete", "create"]
        assert revisions[0]["after"] is None
        assert revisions[0]["before"]["value"] == 35
        # 档案历史保留完整链条：建档、检查记录、指标新增、指标删除。
        profile = client.get(
            f"/api/v1/profiles/{patient_id}/revisions", headers=headers
        ).json()
        assert profile["count"] == 4
        assert {item["entity_type"] for item in profile["revisions"]} == {
            "patient",
            "health_check",
            "lab_metric",
        }


def test_qualitative_and_text_values_are_supported(test_app, db_session):
    make_account(db_session, "doctor-a")
    seed_dictionary(db_session, code="URINE_PROTEIN", value_type=ValueType.QUALITATIVE)
    seed_dictionary(db_session, code="US_LIVER", value_type=ValueType.TEXT)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        check = create_check(client, headers, patient_id)

        qualitative = client.post(
            "/api/v1/lab-metrics",
            json={
                "health_check_id": check["id"],
                "metric_code": "URINE_PROTEIN",
                "original_name": "尿蛋白",
                "canonical_name": "尿蛋白定性",
                "original_value": "+",
                "value_type": "qualitative",
                "qualitative_value": "+",
                "status": "high",
                "normalization_status": "normalized",
                "normalization_version": "v1",
            },
            headers=headers,
        )
        assert qualitative.status_code == 201, qualitative.text
        assert qualitative.json()["qualitative_value"] == "+"
        assert qualitative.json()["value"] is None

        # 定性指标缺结果、数值指标混填定性值都应被拒绝。
        missing = client.post(
            "/api/v1/lab-metrics",
            json={
                "health_check_id": check["id"],
                "metric_code": "URINE_PROTEIN",
                "original_name": "尿蛋白",
                "canonical_name": "尿蛋白定性",
                "original_value": "-",
                "value_type": "qualitative",
                "normalization_status": "normalized",
                "normalization_version": "v1",
            },
            headers=headers,
        )
        assert missing.status_code == 422
        conflict = client.post(
            "/api/v1/lab-metrics",
            json={
                "health_check_id": check["id"],
                "metric_code": "ALT",
                "original_name": "ALT",
                "canonical_name": "丙氨酸氨基转移酶",
                "original_value": "35",
                "value": 35,
                "value_type": "numeric",
                "qualitative_value": "偏高",
                "normalization_status": "normalized",
                "normalization_version": "v1",
            },
            headers=headers,
        )
        assert conflict.status_code == 422

        text = client.post(
            "/api/v1/lab-metrics",
            json={
                "health_check_id": check["id"],
                "metric_code": "US_LIVER",
                "original_name": "肝胆超声",
                "canonical_name": "肝胆超声结论",
                "original_value": "肝内未见明确异常回声",
                "value_type": "text",
                "normalization_status": "normalized",
                "normalization_version": "v1",
            },
            headers=headers,
        )
        assert text.status_code == 201, text.text
        assert text.json()["original_value"] == "肝内未见明确异常回声"


def test_revision_history_respects_patient_ownership(test_app, db_session):
    make_account(db_session, "doctor-a")
    make_account(db_session, "doctor-b")
    seed_dictionary(db_session)
    with TestClient(test_app) as client:
        headers_a = login(client, "doctor-a")
        headers_b = login(client, "doctor-b")
        patient_id = create_patient(client, headers_a)
        check = create_check(client, headers_a, patient_id)
        metric = client.post(
            "/api/v1/lab-metrics",
            json={
                "health_check_id": check["id"],
                "metric_code": "ALT",
                "original_name": "ALT",
                "canonical_name": "丙氨酸氨基转移酶",
                "original_value": "35",
                "value": 35,
                "normalization_status": "normalized",
                "normalization_version": "v1",
            },
            headers=headers_a,
        ).json()

        assert (
            client.get(f"/api/v1/profiles/{patient_id}/revisions", headers=headers_b).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/v1/records/lab_metric/{metric['id']}/revisions", headers=headers_b
            ).status_code
            == 403
        )
        unknown = client.get("/api/v1/records/unknown_type/x/revisions", headers=headers_a)
        assert unknown.status_code == 422


def test_legacy_rows_remain_readable_after_backfill(db_session):
    """旧记录没有来源与值类型：默认 manual / numeric / revision 1，仍可读取。"""

    patient = create_legacy_patient(db_session)
    assert patient.owner_account_id is None
    definition = seed_dictionary(db_session)
    assert definition.value_type is ValueType.NUMERIC

    from app.models import HealthCheck

    check = HealthCheck(patient_id=patient.id, check_date=date(2026, 1, 1))
    db_session.add(check)
    db_session.commit()
    db_session.refresh(check)
    assert check.source_kind == "manual"
    assert check.revision_no == 1

    metric = LabMetric(
        health_check_id=check.id,
        metric_code="ALT",
        original_name="ALT",
        canonical_name="丙氨酸氨基转移酶",
        original_value="35",
        value=35,
        normalization_status="normalized",
        normalization_version="v1",
    )
    db_session.add(metric)
    db_session.commit()
    db_session.refresh(metric)
    assert metric.value_type is ValueType.NUMERIC
    assert metric.revision_no == 1
    assert db_session.scalars(select(RecordRevision)).all() == []


def create_legacy_patient(db):
    from app.models import Patient

    patient = Patient(anonymous_code="P-LEGACY-T02", gender=Gender.UNKNOWN)
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def test_unknown_unit_and_source_survive_persistence(test_app, db_session):
    """H03/H04 交接：单位未知、原始值未知来源都必须原样落库，不能被猜测成标准单位。

    审核要求 T02 明确未知单位/文字与定性值/来源的落库行为；此处用
    ``unsupported_unit`` 与 ``unmapped_metric`` 两种真实异常路径验证：
    原值、原单位与来源说明保留，标准单位与数值保持为空，不产生假换算。
    """

    make_account(db_session, "doctor-a")
    for code, name, unit in (("HGB", "血红蛋白", "g/L"), ("LAB_X_9", "未登记项目", None)):
        db_session.add(
            MetricDictionary(
                metric_code=code,
                canonical_name=name,
                aliases=[],
                standard_unit=unit,
                category="血液",
                value_type=ValueType.NUMERIC,
                unit_conversions={},
                source="测试来源",
                version="v1",
            )
        )
    db_session.commit()
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        patient_id = create_patient(client, headers)
        check = create_check(client, headers, patient_id, source_ref="H04 抽取：第 3 页表 2")

        unknown_unit = client.post(
            "/api/v1/lab-metrics",
            json={
                "health_check_id": check["id"],
                "metric_code": "HGB",
                "original_name": "血红蛋白",
                "canonical_name": "血红蛋白",
                "original_value": "14.2",
                "original_unit": "g/dl(?)",
                "status": "unknown",
                "normalization_status": "unsupported_unit",
                "normalization_version": "v1",
                "source_kind": "import",
                "source_ref": "H04 抽取：第 3 页表 2",
            },
            headers=headers,
        )
        assert unknown_unit.status_code == 201, unknown_unit.text
        body = unknown_unit.json()
        assert body["original_unit"] == "g/dl(?)"
        assert body["standard_unit"] is None
        assert body["value"] is None
        assert body["source_kind"] == "import"
        assert body["source_ref"] == "H04 抽取：第 3 页表 2"

        unmapped = client.post(
            "/api/v1/lab-metrics",
            json={
                "health_check_id": check["id"],
                "metric_code": "LAB_X_9",
                "original_name": "未登记项目",
                "canonical_name": "未登记项目",
                "original_value": "3.3",
                "original_unit": "mmol/L",
                "status": "unknown",
                "normalization_status": "unmapped_metric",
                "normalization_version": "v1",
                "source_kind": "import",
            },
            headers=headers,
        )
        assert unmapped.status_code == 201, unmapped.text
        assert unmapped.json()["metric_code"] == "LAB_X_9"

        revisions = db_session.scalars(select(RecordRevision)).all()
        imported = [item for item in revisions if item.source_kind == "import"]
        assert imported and all(item.after is not None for item in imported)
        stored = db_session.scalar(select(LabMetric).where(LabMetric.metric_code == "HGB"))
        assert stored is not None and stored.standard_unit is None and stored.value is None
