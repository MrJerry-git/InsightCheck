"""T06/T07：三档方案、价格接入、编辑复算、审核与快照稳定性。"""

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
    Plan,
    PlanRevision,
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


def seed_catalog(db):
    items = {
        "CHEST_CT": ("胸部 CT", "影像检查", True, CostLevel.HIGH, 48000),
        "LIVER_FUNCTION_PANEL": ("肝功能组合", "实验室检查", False, CostLevel.LOW, 8000),
        "LIPID_PANEL": ("血脂组合", "实验室检查", False, CostLevel.LOW, 6000),
        "URINE_ROUTINE": ("尿常规", "实验室检查", False, CostLevel.LOW, 3000),
    }
    created = {}
    for code, (name, category, radiation, cost, cents) in items.items():
        item = ExamItem(code=code, name=name, category=category, radiation=radiation,
                        cost_level=cost)
        db.add(item)
        db.flush()
        db.add(
            ExamItemPriceRecord(
                exam_item_id=item.id,
                amount_cents=cents,
                currency="CNY",
                source="测试价目表",
                source_url="https://example.org/price",
                effective_from=date(2025, 1, 1),
                is_demo_price=False,
            )
        )
        created[code] = item
    db.commit()
    return created


def seed_dictionary(db, code, name, category="肝肾功能及生化"):
    db.add(
        MetricDictionary(
            metric_code=code,
            canonical_name=name,
            aliases=[],
            standard_unit="U/L",
            category=category,
            value_type=ValueType.NUMERIC,
            unit_conversions={},
            source="测试来源",
            version="v1",
        )
    )
    db.commit()


def seed_patient(db, owner, code="P-PLAN-001"):
    patient = Patient(
        anonymous_code=code,
        gender=Gender.MALE,
        birth_date=date(1975, 3, 1),
        owner_account_id=owner.id,
    )
    db.add(patient)
    db.commit()
    return patient


def seed_abnormal(db, patient):
    check = HealthCheck(patient_id=patient.id, check_date=date(2026, 1, 5), source_kind="import")
    db.add(check)
    db.flush()
    db.add(
        LabMetric(
            health_check_id=check.id,
            metric_code="ALT",
            original_name="ALT",
            canonical_name="丙氨酸氨基转移酶",
            original_value="88",
            value=88.0,
            reference_min=0.0,
            reference_max=40.0,
            status=MetricStatus.HIGH,
            normalization_status="normalized",
            normalization_version="v1",
        )
    )
    db.commit()
    return check


def prepare(db):
    owner = make_account(db, "doctor-a")
    seed_catalog(db)
    seed_dictionary(db, "ALT", "丙氨酸氨基转移酶")
    patient = seed_patient(db, owner)
    seed_abnormal(db, patient)
    return owner, patient


def create_run(client, headers, patient_id, as_of="2026-02-01"):
    response = client.post(
        "/api/v1/analyses",
        json={"patient_id": patient_id, "as_of_date": as_of},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_plan_builds_three_tiers_with_real_prices(test_app, db_session):
    _, patient = prepare(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        run = create_run(client, headers, patient.id)
        response = client.post(
            "/api/v1/plans",
            json={"patient_id": patient.id, "analysis_run_id": run["run_id"]},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        plan = response.json()
        assert plan["status"] == "draft"
        assert plan["revision_no"] == 1
        assert [tier["tier"] for tier in plan["tiers"]] == ["simplified", "standard", "deep"]
        assert plan["price_catalog_version"]

        simplified = plan["tiers"][0]
        assert simplified["cost_summary"]["known_total_cents"] is not None
        assert simplified["cost_summary"]["is_complete"] is True
        assert all(item["tier"] == "simplified" for item in simplified["items"])
        # 基础档不含辐射项目，深入档才允许。
        assert all(not item["radiation"] for item in simplified["items"])
        deep = plan["tiers"][2]
        assert any(item["radiation"] for item in deep["items"]) or deep["items"] == []
        for item in simplified["items"]:
            assert item["price"]["source"] == "测试价目表"
            assert item["price"]["source_url"] == "https://example.org/price"
            assert item["rule_status"] in {
                "ALLOWED",
                "REVIEW_REQUIRED",
                "NOT_CONFIGURED",
            }

        coverage = client.get(f"/api/v1/plans/{plan['plan_id']}/price-known", headers=headers)
        assert coverage.status_code == 200
        assert coverage.json()["price_catalog_version"] == plan["price_catalog_version"]


def test_unknown_price_does_not_fake_total(test_app, db_session):
    _, patient = prepare(db_session)
    unpriced = ExamItem(
        code="NO_PRICE_ITEM", name="未定价项目", category="实验室检查", cost_level=CostLevel.LOW
    )
    db_session.add(unpriced)
    db_session.commit()

    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        run = create_run(client, headers, patient.id)
        plan = client.post(
            "/api/v1/plans",
            json={"patient_id": patient.id, "analysis_run_id": run["run_id"]},
            headers=headers,
        ).json()
        # 未定价项目不会出现在已定价统计里，也不冒充完整总价。
        for tier in plan["tiers"]:
            unpriced_codes = tier["cost_summary"]["unpriced_item_codes"]
            if unpriced_codes:
                assert "NO_PRICE_ITEM" in unpriced_codes
                assert tier["cost_summary"]["is_complete"] is False
                assert "未知" in tier["cost_summary"]["disclosure"]


def test_budget_recalculation_and_conflicts(test_app, db_session):
    _, patient = prepare(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        run = create_run(client, headers, patient.id)
        plan = client.post(
            "/api/v1/plans",
            json={
                "patient_id": patient.id,
                "analysis_run_id": run["run_id"],
                "budget_limit_cents": 5000,
                "budget_currency": "CNY",
            },
            headers=headers,
        ).json()
        assert plan["budget"]["limit_cents"] == 5000
        deep = plan["tiers"][2]
        assert deep["budget_status"] in {"over_budget", "unknown_prices", "within_budget"}

        # 调整预算触发复算并生成新修订，价格与预算来自服务端。
        edited = client.patch(
            f"/api/v1/plans/{plan['plan_id']}",
            json={"reason": "用户提高预算上限", "budget_limit_cents": 200000},
            headers=headers,
        )
        assert edited.status_code == 200, edited.text
        body = edited.json()
        assert body["revision_no"] == 2
        assert body["budget"]["limit_cents"] == 200000
        assert body["tiers"][2]["budget_status"] != "unknown_prices"


def test_edit_requires_reason_and_regenerates_revision(test_app, db_session):
    _, patient = prepare(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        run = create_run(client, headers, patient.id)
        plan = client.post(
            "/api/v1/plans",
            json={"patient_id": patient.id, "analysis_run_id": run["run_id"]},
            headers=headers,
        ).json()
        missing_reason = client.patch(
            f"/api/v1/plans/{plan['plan_id']}",
            json={"reason": " ", "remove_exam_codes": ["URINE_ROUTINE"]},
            headers=headers,
        )
        assert missing_reason.status_code == 422

        removed = client.patch(
            f"/api/v1/plans/{plan['plan_id']}",
            json={"reason": "患者拒绝尿检", "remove_exam_codes": ["URINE_ROUTINE"]},
            headers=headers,
        )
        assert removed.status_code == 200, removed.text
        body = removed.json()
        assert body["revision_no"] == 2
        codes = {item["code"] for tier in body["tiers"] for item in tier["items"]}
        assert "URINE_ROUTINE" not in codes
        assert "URINE_ROUTINE" in body["manual_exclusions"] or any(
            exclusion["code"] == "URINE_ROUTINE"
            for exclusion in body["manual_exclusions"].values()
        )

        added = client.patch(
            f"/api/v1/plans/{plan['plan_id']}",
            json={"reason": "补充血脂评估", "add_exam_codes": ["LIPID_PANEL"]},
            headers=headers,
        )
        assert added.status_code == 200, added.text
        assert added.json()["revision_no"] == 3
        codes = {item["code"] for tier in added.json()["tiers"] for item in tier["items"]}
        assert "LIPID_PANEL" in codes

        unknown = client.patch(
            f"/api/v1/plans/{plan['plan_id']}",
            json={"reason": "加入不存在的项目", "add_exam_codes": ["NOT_EXIST"]},
            headers=headers,
        )
        assert unknown.status_code == 404


def test_revisions_are_immutable_when_prices_change(test_app, db_session):
    _, patient = prepare(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        run = create_run(client, headers, patient.id)
        plan = client.post(
            "/api/v1/plans",
            json={"patient_id": patient.id, "analysis_run_id": run["run_id"]},
            headers=headers,
        ).json()
        first_total = plan["tiers"][0]["cost_summary"]["known_total_cents"]
        first_catalog = plan["price_catalog_version"]

        price = db_session.scalar(
            select(ExamItemPriceRecord).where(ExamItemPriceRecord.amount_cents == 8000)
        )
        price.amount_cents = 15000
        db_session.commit()

        revisions = client.get(
            f"/api/v1/plans/{plan['plan_id']}/revisions", headers=headers
        ).json()
        assert [item["revision_no"] for item in revisions] == [1]

        old = client.get(
            f"/api/v1/plans/{plan['plan_id']}/revisions/1", headers=headers
        ).json()
        assert old["price_catalog_version"] == first_catalog
        first_revision_total = old["snapshot"]["tiers_result"][0]["cost_summary"]
        assert first_revision_total["known_total_cents"] == first_total

        # 新修订使用新价格，旧修订保持原样。
        edited = client.patch(
            f"/api/v1/plans/{plan['plan_id']}",
            json={"reason": "价格目录更新后复算"},
            headers=headers,
        ).json()
        assert edited["price_catalog_version"] != first_catalog
        assert edited["revision_no"] == 2
        untouched = client.get(
            f"/api/v1/plans/{plan['plan_id']}/revisions/1", headers=headers
        ).json()
        untouched_total = untouched["snapshot"]["tiers_result"][0]["cost_summary"]
        assert untouched_total["known_total_cents"] == first_total


def test_review_confirm_and_permissions(test_app, db_session):
    owner, patient = prepare(db_session)
    make_account(db_session, "doctor-b")
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        other = login(client, "doctor-b")
        run = create_run(client, headers, patient.id)
        plan = client.post(
            "/api/v1/plans",
            json={"patient_id": patient.id, "analysis_run_id": run["run_id"]},
            headers=headers,
        ).json()
        assert client.get(f"/api/v1/plans/{plan['plan_id']}", headers=other).status_code == 403

        early = client.post(f"/api/v1/plans/{plan['plan_id']}/confirm", headers=headers)
        assert early.status_code == 409
        review = client.post(f"/api/v1/plans/{plan['plan_id']}/submit-review", headers=headers)
        assert review.status_code == 200
        assert review.json()["status"] == "review"
        confirmed = client.post(f"/api/v1/plans/{plan['plan_id']}/confirm", headers=headers)
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"
        # 已确认方案不能直接编辑，避免覆盖已确认版本。
        locked = client.patch(
            f"/api/v1/plans/{plan['plan_id']}",
            json={"reason": "试图修改已确认方案"},
            headers=headers,
        )
        assert locked.status_code == 409
        assert len(db_session.scalars(select(PlanRevision)).all()) == 1
        assert db_session.scalar(select(Plan)).status.value == "confirmed"


def test_plan_rejects_stale_analysis(test_app, db_session):
    owner, patient = prepare(db_session)
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        run = create_run(client, headers, patient.id)
        metric = db_session.scalar(select(LabMetric))
        metric.value = 150.0
        db_session.commit()

        stale = client.post(
            "/api/v1/plans",
            json={"patient_id": patient.id, "analysis_run_id": run["run_id"]},
            headers=headers,
        )
        assert stale.status_code == 409
        assert "重新分析" in stale.json()["detail"]

        fresh = create_run(client, headers, patient.id)
        assert fresh["run_id"] != run["run_id"]
        plan = client.post(
            "/api/v1/plans",
            json={"patient_id": patient.id, "analysis_run_id": fresh["run_id"]},
            headers=headers,
        )
        assert plan.status_code == 201
