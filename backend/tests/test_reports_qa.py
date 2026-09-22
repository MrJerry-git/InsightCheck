"""T09/T10：中文 PDF 报告、JSON 证据导出与依据问答。"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    ExamItem,
    ExamItemPriceRecord,
    HealthCheck,
    LabMetric,
    MetricDictionary,
    Patient,
    QaRecord,
    ReportExport,
)
from app.models.enums import AccountRole, CostLevel, Gender, MetricStatus, ValueType
from app.services.auth_service import AuthService

DOCTOR_PASSWORD = "Doctor-Pass-2026!"


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


def prepare(db, owner, suffix=""):
    item = ExamItem(
        code=f"LIVER_FUNCTION_PANEL{suffix}", name="肝功能组合", category="实验室检查",
        cost_level=CostLevel.LOW,
    )
    db.add(item)
    db.flush()
    db.add(
        ExamItemPriceRecord(
            exam_item_id=item.id,
            amount_cents=8000,
            currency="CNY",
            source="测试机构价目表",
            source_url="https://example.org/price",
            effective_from=date(2025, 1, 1),
            is_demo_price=False,
        )
    )
    db.add(
        MetricDictionary(
            metric_code=f"ALT{suffix}", canonical_name="丙氨酸氨基转移酶", aliases=[],
            standard_unit="U/L", category="肝肾功能及生化", value_type=ValueType.NUMERIC,
            unit_conversions={}, source="目录来源", version="v1",
        )
    )
    patient = Patient(
        anonymous_code=f"P-REPORT-001{suffix}", gender=Gender.MALE,
        birth_date=date(1975, 3, 1), owner_account_id=owner.id,
    )
    db.add(patient)
    db.flush()
    check = HealthCheck(patient_id=patient.id, check_date=date(2026, 1, 5), source_kind="import")
    db.add(check)
    db.flush()
    db.add(
        LabMetric(
            health_check_id=check.id, metric_code=f"ALT{suffix}", original_name="ALT",
            canonical_name="丙氨酸氨基转移酶", original_value="88", value=88.0,
            reference_min=0.0, reference_max=40.0, status=MetricStatus.HIGH,
            normalization_status="normalized", normalization_version="v1",
            source_kind="import", source_ref="import_task:t1#r1",
        )
    )
    db.commit()
    return patient


def build_plan(client, headers, patient_id):
    run = client.post(
        "/api/v1/analyses",
        json={"patient_id": patient_id, "as_of_date": "2026-02-01"},
        headers=headers,
    )
    assert run.status_code == 201, run.text
    plan = client.post(
        "/api/v1/plans",
        json={"patient_id": patient_id, "analysis_run_id": run.json()["run_id"]},
        headers=headers,
    )
    assert plan.status_code == 201, plan.text
    return run.json(), plan.json()


def test_report_pdf_is_chinese_readable_and_recorded(test_app, db_session):
    owner = make_account(db_session, "doctor-a")
    patient = prepare(db_session, owner)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        _, plan = build_plan(client, headers, patient.id)

        document = client.get(f"/api/v1/reports/{plan['plan_id']}", headers=headers)
        assert document.status_code == 200, document.text
        body = document.json()
        assert body["patient_code"] == "P-REPORT-001"
        assert body["revision_no"] == 1
        assert body["price_catalog_version"] == plan["price_catalog_version"]
        assert body["analysis"]["model_status"].startswith("未评估")

        response = client.get(f"/api/v1/reports/{plan['plan_id']}/pdf", headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        payload = response.content
        assert payload.startswith(b"%PDF-1.4")
        assert b"/UniGB-UCS2-H" in payload  # 中文标准字体，无需随包分发字体文件
        title = "循影定检".encode("utf-16-be").hex().upper().encode()
        assert title in payload
        patient_code = "P-REPORT-001".encode("utf-16-be").hex().upper().encode()
        assert patient_code in payload
        assert payload.rstrip().endswith(b"%%EOF")

        export = db_session.scalar(select(ReportExport))
        assert export.revision_no == 1
        assert export.size_bytes == len(payload)
        assert export.content_sha256

        evidence = client.get(
            f"/api/v1/reports/{plan['plan_id']}/evidence", headers=headers
        ).json()
        assert evidence["evidence"]["records"]
        assert evidence["evidence"]["prices"][0]["source_url"].startswith("https://")


def test_report_revision_matches_snapshot(test_app, db_session):
    owner = make_account(db_session, "doctor-a")
    patient = prepare(db_session, owner)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        _, plan = build_plan(client, headers, patient.id)
        first_price_version = plan["price_catalog_version"]
        client.patch(
            f"/api/v1/plans/{plan['plan_id']}",
            json={"reason": "补充说明后重新生成"},
            headers=headers,
        )
        old = client.get(
            f"/api/v1/reports/{plan['plan_id']}?revision_no=1", headers=headers
        ).json()
        assert old["revision_no"] == 1
        assert old["price_catalog_version"] == first_price_version
        latest = client.get(f"/api/v1/reports/{plan['plan_id']}", headers=headers).json()
        assert latest["revision_no"] == 2


def test_report_and_qa_permissions(test_app, db_session):
    owner = make_account(db_session, "doctor-a")
    make_account(db_session, "doctor-b")
    patient = prepare(db_session, owner)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        other = login(client, "doctor-b")
        _, plan = build_plan(client, headers, patient.id)
        assert (
            client.get(f"/api/v1/reports/{plan['plan_id']}/pdf", headers=other).status_code == 403
        )
        assert (
            client.get(f"/api/v1/reports/{plan['plan_id']}", headers=other).status_code == 403
        )
        assert (
            client.post(
                "/api/v1/qa/ask",
                json={"patient_id": patient.id, "question": "费用多少"},
                headers=other,
            ).status_code
            == 403
        )


def test_qa_answers_with_citations_and_never_modifies_plan(test_app, db_session):
    owner = make_account(db_session, "doctor-a")
    patient = prepare(db_session, owner)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        _, plan = build_plan(client, headers, patient.id)
        before = client.get(f"/api/v1/plans/{plan['plan_id']}", headers=headers).json()

        cost = client.post(
            "/api/v1/qa/ask",
            json={
                "patient_id": patient.id,
                "plan_id": plan["plan_id"],
                "question": "这三个档位分别要花多少钱？",
            },
            headers=headers,
        )
        assert cost.status_code == 200, cost.text
        body = cost.json()
        assert body["provider"] == "structured-local-v1"
        assert body["can_modify_plan"] is False
        assert "预算状态" in body["answer"]
        assert body["citations"]
        assert {item["type"] for item in body["citations"]} & {"plan_revision", "price"}

        risk = client.post(
            "/api/v1/qa/ask",
            json={
                "patient_id": patient.id,
                "plan_id": plan["plan_id"],
                "question": "我的肺癌风险是多少",
            },
            headers=headers,
        ).json()
        assert "未评估" in risk["answer"]
        assert "概率" in risk["answer"]

        reason = client.post(
            "/api/v1/qa/ask",
            json={
                "patient_id": patient.id,
                "plan_id": plan["plan_id"],
                "question": "为什么推荐这些项目？",
            },
            headers=headers,
        ).json()
        assert "纳入理由" in reason["answer"]
        assert any(item["type"] in {"rule", "plan_revision"} for item in reason["citations"])

        follow_up = client.post(
            "/api/v1/qa/ask",
            json={
                "patient_id": patient.id,
                "plan_id": plan["plan_id"],
                "question": "需要多久复查？",
            },
            headers=headers,
        ).json()
        assert follow_up["answer"]
        assert "编造" in follow_up["answer"] or "随访" in follow_up["answer"]

        # 问答不修改方案：快照与修订号不变。
        after = client.get(f"/api/v1/plans/{plan['plan_id']}", headers=headers).json()
        assert after["revision_no"] == before["revision_no"]
        assert after["tiers"] == before["tiers"]
        assert len(db_session.scalars(select(QaRecord)).all()) == 4

        history = client.get(
            f"/api/v1/qa/history?patient_id={patient.id}", headers=headers
        ).json()
        assert len(history) == 4
        assert history[0]["question"]


def test_qa_request_id_is_idempotent(test_app, db_session):
    owner = make_account(db_session, "doctor-a")
    patient = prepare(db_session, owner)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        _, plan = build_plan(client, headers, patient.id)
        payload = {
            "patient_id": patient.id,
            "plan_id": plan["plan_id"],
            "question": "有哪些项目？",
            "request_id": "qa-1",
        }
        first = client.post("/api/v1/qa/ask", json=payload, headers=headers).json()
        second = client.post("/api/v1/qa/ask", json=payload, headers=headers).json()
        assert first["qa_id"] == second["qa_id"]
        assert len(db_session.scalars(select(QaRecord)).all()) == 1


def test_model_answer_with_invalid_citation_falls_back(test_app, db_session, monkeypatch):
    """模型引用了不存在的依据时必须退回结构化回答，而不是照抄。"""

    owner = make_account(db_session, "doctor-a")
    patient = prepare(db_session, owner)
    monkeypatch.setattr(
        "app.services.qa.get_settings",
        lambda: type(
            "S",
            (),
            {
                "llm_provider": "openai-compatible",
                "llm_model": "test-model",
                "llm_base_url": "http://127.0.0.1:9",
                "llm_api_key": None,
                "llm_timeout": 1.0,
            },
        )(),
    )
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        _, plan = build_plan(client, headers, patient.id)
        response = client.post(
            "/api/v1/qa/ask",
            json={"patient_id": patient.id, "plan_id": plan["plan_id"], "question": "依据是什么"},
            headers=headers,
        )
        assert response.status_code == 200
        # 模型不可达 → 结构化回答，仍带可追溯引用。
        assert response.json()["provider"] == "structured-local-v1"
        assert response.json()["citations"]


def test_qa_request_id_cannot_leak_across_accounts(test_app, db_session):
    """审核 P1：两个账号用同一 request_id 时，第二个账号不能收到第一个档案的问答。"""

    owner = make_account(db_session, "doctor-a")
    other = make_account(db_session, "doctor-b")
    patient_a = prepare(db_session, owner)
    patient_b = prepare(db_session, other, suffix="-B")
    with TestClient(test_app) as client:
        headers_a = login(client, "doctor-a")
        headers_b = login(client, "doctor-b")
        _, plan_a = build_plan(client, headers_a, patient_a.id)
        _, plan_b = build_plan(client, headers_b, patient_b.id)

        first = client.post(
            "/api/v1/qa/ask",
            json={
                "patient_id": patient_a.id,
                "plan_id": plan_a["plan_id"],
                "question": "这个方案有哪些项目？",
                "request_id": "shared-request-id",
            },
            headers=headers_a,
        )
        assert first.status_code == 200, first.text

        leak = client.post(
            "/api/v1/qa/ask",
            json={
                "patient_id": patient_b.id,
                "plan_id": plan_b["plan_id"],
                "question": "这个方案有哪些项目？",
                "request_id": "shared-request-id",
            },
            headers=headers_b,
        )
        assert leak.status_code == 409, leak.text
        assert "request_id" in leak.json()["detail"]

        # 同一账号重复提问仍然幂等，不重复落库。
        again = client.post(
            "/api/v1/qa/ask",
            json={
                "patient_id": patient_a.id,
                "plan_id": plan_a["plan_id"],
                "question": "这个方案有哪些项目？",
                "request_id": "shared-request-id",
            },
            headers=headers_a,
        )
        assert again.status_code == 200
        assert again.json()["qa_id"] == first.json()["qa_id"]
        assert len(db_session.scalars(select(QaRecord)).all()) == 1


def test_report_evidence_is_frozen_after_records_change(test_app, db_session):
    """审核 P1：历史报告与问答的证据必须来自生成时的快照，不随当前数据变化。"""

    from app.models import MedicalRule
    from app.models.enums import RuleAction

    owner = make_account(db_session, "doctor-a")
    patient = prepare(db_session, owner)
    item = db_session.scalar(select(ExamItem).where(ExamItem.code == "LIVER_FUNCTION_PANEL"))
    db_session.add(
        MedicalRule(
            rule_code="LIVER.LONG_INTERVAL",
            rule_type="INTERVAL",
            exam_item_id=item.id,
            condition_json={"minimum_months": 24},
            action=RuleAction.ALLOW,
            priority=10,
            source="原规则来源（2026-01）",
            version="v1",
            enabled=True,
        )
    )
    db_session.commit()

    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        _, plan = build_plan(client, headers, patient.id)
        first = client.get(f"/api/v1/reports/{plan['plan_id']}", headers=headers).json()
        first_evidence = first["evidence"]
        assert first_evidence["records"], "报告应包含指标依据"
        assert first_evidence["records"][0]["original_value"] == "88"

        # 生成报告后修改指标数值、删除指标记录、更新规则来源。
        metric = db_session.scalar(select(LabMetric))
        metric.original_value = "150"
        metric.value = 150.0
        rule = db_session.scalar(select(MedicalRule))
        rule.source = "被修改后的规则来源"
        db_session.delete(metric)
        db_session.commit()

        again = client.get(f"/api/v1/reports/{plan['plan_id']}", headers=headers).json()
        assert again["evidence"]["records"] == first_evidence["records"]
        # 规则依据同样来自快照：规则被改写后旧报告仍显示当时的来源。
        assert again["evidence"]["rules"] == first_evidence["rules"]
        assert again["evidence"]["snapshot_version"] == "report-evidence-v1"
        assert again["evidence"]["captured_at"] == first_evidence["captured_at"]

        # 问答使用同一份冻结证据，引用仍指向旧版依据。
        answer = client.post(
            "/api/v1/qa/ask",
            json={
                "patient_id": patient.id,
                "plan_id": plan["plan_id"],
                "question": "证据里的指标是多少？",
            },
            headers=headers,
        )
        assert answer.status_code == 200, answer.text
        assert answer.json()["citations"]
        # 问答不会改动已冻结的报告证据。
        after_answer = client.get(f"/api/v1/reports/{plan['plan_id']}", headers=headers).json()
        assert after_answer["evidence"]["records"] == first_evidence["records"]
