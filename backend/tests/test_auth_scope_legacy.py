"""T01 复核补充：推荐明细父级归属、参赛报告归属与旧业务入口鉴权。

对应审核意见：
* ``PATIENT_SCOPE_MODELS`` 漏掉 RecommendationItem，/recommendation-items 可跨账号读写；
* 启用 AUTH_REQUIRED 后参赛报告等旧入口仍无鉴权依赖；
* 参赛档案/报告需要明确的账号归属策略。
"""

import re
from datetime import date

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models import ExamItem, Patient, Recommendation, RecommendationItem
from app.models.enums import (
    AccountRole,
    CostLevel,
    Gender,
    PlanTier,
    RecommendationDecision,
)
from app.models.prevention import PreventionReport
from app.services.auth_service import AuthService

DOCTOR_PASSWORD = "Doctor-Pass-2026!"


def make_account(db, username):
    return AuthService(db, iterations=10_000).create_account(
        username=username,
        password=DOCTOR_PASSWORD,
        display_name=username,
        role=AccountRole.DOCTOR,
    )


def login(client, username):
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": DOCTOR_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def seed_recommendation(db, owner):
    patient = Patient(
        anonymous_code=f"P-{owner.username}",
        gender=Gender.MALE,
        owner_account_id=owner.id,
    )
    item = ExamItem(
        code="CHEST_CT",
        name="胸部 CT",
        category="影像检查",
        radiation=True,
        cost_level=CostLevel.HIGH,
    )
    db.add_all([patient, item])
    db.flush()
    recommendation = Recommendation(
        patient_id=patient.id, plan_tier=PlanTier.STANDARD, trace_id="trace-scope"
    )
    db.add(recommendation)
    db.flush()
    entry = RecommendationItem(
        recommendation_id=recommendation.id,
        exam_item_id=item.id,
        decision=RecommendationDecision.INCLUDE,
    )
    db.add(entry)
    db.commit()
    return patient, recommendation, entry


def prevention_body(label="scope"):
    today = date.today().isoformat()
    return dict(
        label=label,
        sex="female",
        known_cvd=False,
        pregnant=False,
        symptomatic=False,
        source="synthetic",
        source_note="scope test only",
        as_of=today,
        visits=[
            dict(
                date=today,
                age=50,
                sbp=160,
                bp_tx=True,
                total_c=200,
                hdl_c=45,
                chol_unit="mg/dL",
                statin=False,
                dm=True,
                smoking=False,
                egfr=90,
                bmi=35,
                glucose_status="diabetes",
            )
        ],
    )


def test_recommendation_items_follow_parent_ownership(test_app, db_session):
    owner = make_account(db_session, "doctor-a")
    make_account(db_session, "doctor-b")
    _, recommendation, entry = seed_recommendation(db_session, owner)

    with TestClient(test_app) as client:
        headers_owner = login(client, "doctor-a")
        headers_other = login(client, "doctor-b")

        assert len(client.get("/api/v1/recommendation-items", headers=headers_owner).json()) == 1
        assert client.get("/api/v1/recommendation-items", headers=headers_other).json() == []

        path = f"/api/v1/recommendation-items/{entry.id}"
        assert client.get(path, headers=headers_owner).status_code == 200
        assert client.get(path, headers=headers_other).status_code == 404
        assert client.patch(path, json={"rank": 1}, headers=headers_other).status_code == 404
        assert client.delete(path, headers=headers_other).status_code == 404
        # 越权写入既被拒绝，也没有改到已有记录。
        assert client.get(path, headers=headers_owner).json()["rank"] is None

        created = client.post(
            "/api/v1/recommendation-items",
            json={
                "recommendation_id": recommendation.id,
                "exam_item_id": entry.exam_item_id,
                "decision": "include",
                "rank": 2,
            },
            headers=headers_other,
        )
        assert created.status_code == 403


def test_competition_reports_are_owned_by_creator(test_app, db_session):
    make_account(db_session, "doctor-a")
    make_account(db_session, "doctor-b")

    with TestClient(test_app) as client:
        headers_owner = login(client, "doctor-a")
        headers_other = login(client, "doctor-b")

        created = client.post(
            "/api/v1/prevention/reports", json=prevention_body(), headers=headers_owner
        )
        assert created.status_code == 201, created.text
        created_id = created.json()["id"]

        owner_list = client.get("/api/v1/prevention/reports", headers=headers_owner).json()
        assert [row["id"] for row in owner_list] == [created_id]
        assert client.get("/api/v1/prevention/reports", headers=headers_other).json() == []
        assert (
            client.get(
                f"/api/v1/prevention/reports/{created_id}", headers=headers_other
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/v1/prevention/reports/{created_id}", headers=headers_owner
            ).status_code
            == 200
        )
        # 匿名开发模式是显式配置：AUTH_REQUIRED 关闭时才可见全部报告。
        assert len(client.get("/api/v1/prevention/reports").json()) == 1

    stored = db_session.get(PreventionReport, created_id)
    assert stored is not None and stored.owner_account_id is not None


def test_legacy_business_routes_require_token_when_auth_required(monkeypatch, test_app):
    monkeypatch.setattr(
        "app.api.dependencies.get_settings", lambda: Settings(auth_required=True)
    )
    with TestClient(test_app) as client:
        for path in (
            "/api/v1/prevention/reports",
            "/api/v1/imports/patients",
            "/api/v1/lesion-analysis/demo",
            "/api/v1/prevention/smart-import/status",
            "/api/v1/patients",
            "/api/v1/recommendations",
        ):
            assert client.get(path).status_code == 401, path
        assert client.post("/api/v1/prevention/assess", json=prevention_body()).status_code == 401
        assert (
            client.post(
                "/api/v1/lesion-terminology/normalize", json={"location": "右肺上叶"}
            ).status_code
            == 401
        )


PUBLIC_PATHS = {"/health", "/api/v1/health", "/api/v1/auth/login"}


def test_every_api_route_rejects_anonymous_when_auth_required(monkeypatch, test_app):
    """审计全部路由：启用鉴权后，除健康检查与登录外都不能匿名访问。"""

    monkeypatch.setattr(
        "app.api.dependencies.get_settings", lambda: Settings(auth_required=True)
    )
    application = create_app()
    with TestClient(application) as client:
        checked: list[str] = []
        for path, operations in application.openapi()["paths"].items():
            if path in PUBLIC_PATHS:
                continue
            url = re.sub(r"\{[^}]+\}", "probe-id", path)
            for method in ("get", "post", "patch", "delete"):
                if method not in operations:
                    continue
                response = client.request(method.upper(), url, json={})
                assert response.status_code == 401, f"{method.upper()} {url}"
                checked.append(f"{method.upper()} {url}")
    assert len(checked) > 50, f"路由审计覆盖不足：{len(checked)}"
