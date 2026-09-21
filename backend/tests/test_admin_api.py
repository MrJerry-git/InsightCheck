"""T08：管理 API（映射队列、价格生效范围、规则生命周期、模型状态与审计）。"""

from datetime import date

from fastapi.testclient import TestClient

from app.models import (
    AuditEvent,
    ExamItem,
    ExamItemPriceRecord,
    HealthCheck,
    LabMetric,
    MedicalRule,
    MetricDictionary,
    Patient,
)
from app.models.enums import AccountRole, CostLevel, Gender, NormalizationStatus, ValueType
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


def seed_exam_item(db, code="LIVER_FUNCTION_PANEL"):
    item = ExamItem(
        code=code, name="肝功能组合", category="实验室检查", cost_level=CostLevel.LOW
    )
    db.add(item)
    db.commit()
    return item


def seed_pending_metric(db, owner):
    patient = Patient(
        anonymous_code="P-ADMIN-001", gender=Gender.UNKNOWN, owner_account_id=owner.id
    )
    db.add(patient)
    db.flush()
    check = HealthCheck(patient_id=patient.id, check_date=date(2026, 1, 5), source_kind="import")
    db.add(check)
    db.flush()
    placeholder = MetricDictionary(
        metric_code="UNMAPPED",
        canonical_name="未映射指标（待人工映射）",
        aliases=[],
        category="待映射",
        value_type=ValueType.TEXT,
        unit_conversions={},
        source="系统占位",
        version="pending-v1",
    )
    db.add(placeholder)
    db.flush()
    metric = LabMetric(
        health_check_id=check.id,
        metric_code="UNMAPPED",
        original_name="谷丙转氨酶",
        canonical_name="未映射指标（待人工映射）",
        original_value="88",
        value=88.0,
        original_unit="U/L",
        normalization_status=NormalizationStatus.UNMAPPED_METRIC,
        normalization_version="import-task-v1",
        source_kind="import",
        source_ref="import_task:t1#r1",
    )
    db.add(metric)
    db.commit()
    return metric


def test_mapping_queue_and_apply(test_app, db_session):
    doctor = make_account(db_session, "doctor-a")
    make_account(db_session, "admin-a", role=AccountRole.ADMIN)
    seed_exam_item(db_session)
    metric = seed_pending_metric(db_session, doctor)
    db_session.add(
        MetricDictionary(
            metric_code="ALT",
            canonical_name="丙氨酸氨基转移酶",
            aliases=[],
            standard_unit="U/L",
            category="肝肾功能及生化",
            value_type=ValueType.NUMERIC,
            unit_conversions={},
            source="目录来源",
            version="v1",
        )
    )
    db_session.commit()

    with TestClient(test_app) as client:
        admin = login(client, "admin-a", AccountRole.ADMIN)
        doctor_headers = login(client, "doctor-a")
        denied = client.get("/api/v1/admin/metric-mapping-queue", headers=doctor_headers)
        assert denied.status_code == 403
        queue = client.get("/api/v1/admin/metric-mapping-queue", headers=admin).json()
        assert len(queue) == 1
        assert queue[0]["original_name"] == "谷丙转氨酶"
        assert queue[0]["source_ref"] == "import_task:t1#r1"

        missing_code = client.post(
            "/api/v1/admin/metric-mapping",
            json={"mappings": [{"metric_id": metric.id, "metric_code": "NOT_EXIST"}]},
            headers=admin,
        )
        assert missing_code.status_code == 422

        applied = client.post(
            "/api/v1/admin/metric-mapping",
            json={"mappings": [{"metric_id": metric.id, "metric_code": "ALT"}]},
            headers=admin,
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["mapped"][0]["metric_code"] == "ALT"
        db_session.refresh(metric)
        assert metric.metric_code == "ALT"
        assert metric.canonical_name == "丙氨酸氨基转移酶"
        # 映射写入业务修订与审计，两者都可查。
        revisions = client.get(
            f"/api/v1/records/lab_metric/{metric.id}/revisions", headers=admin
        ).json()["revisions"]
        assert revisions[0]["changed_fields"]
        audit = client.get("/api/v1/admin/audit?source=admin", headers=admin).json()
        assert audit["events"][0]["action"] == "metric.mapped"


def test_price_management_requires_source_for_real_price(test_app, db_session):
    make_account(db_session, "admin-a", role=AccountRole.ADMIN)
    seed_exam_item(db_session)
    with TestClient(test_app) as client:
        admin = login(client, "admin-a", AccountRole.ADMIN)
        no_source = client.post(
            "/api/v1/admin/exam-item-prices",
            json={
                "exam_item_code": "LIVER_FUNCTION_PANEL",
                "amount_cents": 8000,
                "source": "机构价目表",
                "effective_from": "2026-01-01",
                "is_demo_price": False,
            },
            headers=admin,
        )
        assert no_source.status_code == 422

        created = client.post(
            "/api/v1/admin/exam-item-prices",
            json={
                "exam_item_code": "LIVER_FUNCTION_PANEL",
                "amount_cents": 8000,
                "source": "机构价目表 2026",
                "source_url": "https://example.org/price/2026",
                "effective_from": "2026-01-01",
                "is_demo_price": False,
            },
            headers=admin,
        )
        assert created.status_code == 201, created.text
        price_id = created.json()["price_id"]

        listing = client.get(
            "/api/v1/admin/exam-item-prices?as_of_date=2026-03-01", headers=admin
        ).json()
        assert listing[0]["amount_cents"] == 8000
        assert listing[0]["source_url"].startswith("https://")
        expired = client.get(
            "/api/v1/admin/exam-item-prices?as_of_date=2025-01-01", headers=admin
        ).json()
        assert expired == []

        bad_range = client.patch(
            f"/api/v1/admin/exam-item-prices/{price_id}",
            json={"effective_to": "2025-12-31"},
            headers=admin,
        )
        assert bad_range.status_code == 422
        updated = client.patch(
            f"/api/v1/admin/exam-item-prices/{price_id}",
            json={"amount_cents": 9000, "effective_to": "2026-12-31"},
            headers=admin,
        )
        assert updated.status_code == 200
        assert db_session.get(ExamItemPriceRecord, price_id).amount_cents == 9000


def test_rule_lifecycle_draft_then_enable(test_app, db_session):
    make_account(db_session, "admin-a", role=AccountRole.ADMIN)
    seed_exam_item(db_session)
    with TestClient(test_app) as client:
        admin = login(client, "admin-a", AccountRole.ADMIN)
        created = client.post(
            "/api/v1/admin/rules",
            json={
                "rule_code": "LIVER_REPEAT_V1",
                "rule_type": "INTERVAL",
                "exam_item_code": "LIVER_FUNCTION_PANEL",
                "condition": {"max_interval_months": 12},
                "action": "ALLOW",
                "source": "工程草稿：待医学审核",
                "version": "1.0.0",
            },
            headers=admin,
        )
        assert created.status_code == 201, created.text
        rule_id = created.json()["rule_id"]
        assert created.json()["enabled"] is False  # 默认草稿，不影响现有结论

        duplicate = client.post(
            "/api/v1/admin/rules",
            json={
                "rule_code": "LIVER_REPEAT_V1",
                "rule_type": "INTERVAL",
                "condition": {},
                "action": "ALLOW",
                "source": "重复",
                "version": "1.0.0",
            },
            headers=admin,
        )
        assert duplicate.status_code == 409

        enabled = client.patch(
            f"/api/v1/admin/rules/{rule_id}",
            json={"enabled": True, "priority": 5},
            headers=admin,
        )
        assert enabled.status_code == 200
        assert db_session.get(MedicalRule, rule_id).enabled is True
        drafts = client.get("/api/v1/admin/rules?enabled=false", headers=admin).json()
        assert drafts == []
        live = client.get("/api/v1/admin/rules", headers=admin).json()
        assert live[0]["rule_code"] == "LIVER_REPEAT_V1"
        assert live[0]["source"].startswith("工程草稿")


def test_model_tasks_report_real_status(test_app, db_session):
    make_account(db_session, "admin-a", role=AccountRole.ADMIN)
    with TestClient(test_app) as client:
        admin = login(client, "admin-a", AccountRole.ADMIN)
        body = client.get("/api/v1/admin/model-tasks", headers=admin).json()
        assert body["provider_version"] == "local-rules-v1"
        statuses = {task["task"]: task for task in body["tasks"]}
        assert statuses["disease_risk_models"]["status"] == "未接入"
        assert statuses["deepfm_ranking"]["status"] == "未接入"
        assert "规则" in statuses["deepfm_ranking"]["detail"]


def test_audit_merges_admin_and_record_events(test_app, db_session):
    doctor = make_account(db_session, "doctor-a")
    make_account(db_session, "admin-a", role=AccountRole.ADMIN)
    seed_exam_item(db_session)
    seed_pending_metric(db_session, doctor)
    with TestClient(test_app) as client:
        admin = login(client, "admin-a", AccountRole.ADMIN)
        # 触发一条记录修订（业务侧）与一条管理审计。
        client.post(
            "/api/v1/admin/exam-item-prices",
            json={
                "exam_item_code": "LIVER_FUNCTION_PANEL",
                "amount_cents": 100,
                "source": "演示价来源",
                "effective_from": "2026-01-01",
                "is_demo_price": True,
            },
            headers=admin,
        )
        events = client.get("/api/v1/admin/audit?limit=50", headers=admin).json()["events"]
        sources = {event["source"] for event in events}
        assert "admin" in sources
        only_admin = client.get("/api/v1/admin/audit?source=admin", headers=admin).json()
        assert all(event["source"] == "admin" for event in only_admin["events"])
        assert len(db_session.query(AuditEvent).all()) >= 1
