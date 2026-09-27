"""T12：后端整体联调链路（登录 → 导入 → 分析 → 方案 → 报告 → 问答 → 退出）。

使用普通新建档案（不是预置演示病人），每一环都走真实接口与真实数据库，
不依赖任何外部模型服务：CSV 导入走确定性解析，问答走结构化回答。
"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    Account,
    ExamItem,
    ExamItemPriceRecord,
    LabMetric,
    MetricDictionary,
    PlanRevision,
    RecordRevision,
)
from app.models.enums import AccountRole, CostLevel, ValueType
from app.services.auth_service import AuthService

ADMIN_PASSWORD = "Admin-Pass-2026!"
DOCTOR_PASSWORD = "Doctor-Pass-2026!"
CSV_HEADER = "date,metric_code,original_name,value,unit,reference_min,reference_max\n"


def seed_catalog_and_dictionary(db):
    """机构目录、价格与指标字典：真实链路所需的配置数据。"""

    items = {
        "LIVER_FUNCTION_PANEL": ("肝功能组合", "实验室检查", CostLevel.LOW, 8000),
        "LIPID_PANEL": ("血脂组合", "实验室检查", CostLevel.LOW, 6000),
        "URINE_ROUTINE": ("尿常规", "实验室检查", CostLevel.LOW, 3000),
    }
    for code, (name, category, cost, cents) in items.items():
        item = ExamItem(code=code, name=name, category=category, cost_level=cost)
        db.add(item)
        db.flush()
        db.add(
            ExamItemPriceRecord(
                exam_item_id=item.id,
                amount_cents=cents,
                currency="CNY",
                source="机构价目表 2026",
                source_url="https://example.org/price/2026",
                effective_from=date(2026, 1, 1),
                is_demo_price=False,
            )
        )
    for code, name, unit in (
        ("ALT", "丙氨酸氨基转移酶", "U/L"),
        ("TC", "总胆固醇", "mmol/L"),
    ):
        db.add(
            MetricDictionary(
                metric_code=code,
                canonical_name=name,
                aliases=[],
                standard_unit=unit,
                category="肝肾功能及生化",
                value_type=ValueType.NUMERIC,
                unit_conversions={},
                source="机构检验目录 2026",
                version="v1",
            )
        )
    db.commit()


def test_full_backend_chain(tmp_path, monkeypatch, test_app, db_session):
    monkeypatch.setattr(
        "app.services.import_tasks.get_settings",
        lambda: type("S", (), {"import_task_storage_dir": str(tmp_path / "tasks")})(),
    )
    audit = AuthService(db_session, iterations=10_000)
    audit.create_account(
        username="admin-a",
        password=ADMIN_PASSWORD,
        display_name="管理员",
        role=AccountRole.ADMIN,
    )
    audit.create_account(
        username="doctor-a",
        password=DOCTOR_PASSWORD,
        display_name="医生 A",
        role=AccountRole.DOCTOR,
    )
    seed_catalog_and_dictionary(db_session)

    with TestClient(test_app) as client:
        # 1. 登录
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "doctor-a", "password": DOCTOR_PASSWORD},
        )
        assert login.status_code == 200, login.text
        doctor = {"Authorization": f"Bearer {login.json()['token']}"}
        assert client.get("/api/v1/auth/me", headers=doctor).json()["username"] == "doctor-a"

        # 2. 新建普通档案（不是演示病人）
        created = client.post(
            "/api/v1/patients",
            json={
                "anonymous_code": "P-E2E-001",
                "gender": "male",
                "birth_date": "1975-03-01",
                "height": 172.0,
            },
            headers=doctor,
        )
        assert created.status_code == 201, created.text
        patient_id = created.json()["id"]

        # 3. 上传报告 → 逐字段校对 → 确认入库
        csv_body = CSV_HEADER + (
            "2026-01-05,ALT,丙氨酸氨基转移酶,88,U/L,0,40\n"
            "2026-01-05,TC,总胆固醇,6.2,mmol/L,3.0,5.2\n"
        )
        upload = client.post(
            "/api/v1/imports/tasks",
            data={"patient_id": patient_id, "request_id": "e2e-upload-1"},
            files={"file": ("report.csv", csv_body.encode("utf-8"), "text/csv")},
            headers=doctor,
        )
        assert upload.status_code == 201, upload.text
        task = upload.json()
        assert task["status"] == "preview_ready"
        assert task["rows"][0]["source_ref"] == "第 2 行"
        confirmed = client.post(
            f"/api/v1/imports/tasks/{task['task_id']}/confirm", json={}, headers=doctor
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["result"]["created_metric_count"] == 2

        # 4. 分析：跨系统发现与候选
        analysis = client.post(
            "/api/v1/analyses",
            json={"patient_id": patient_id, "as_of_date": "2026-02-01"},
            headers=doctor,
        )
        assert analysis.status_code == 201, analysis.text
        run = analysis.json()
        assert run["stale"] is False
        assert run["summary"]["candidate_count"] >= 1
        liver_candidate = [
            item for item in run["candidates"] if item["code"] == "LIVER_FUNCTION_PANEL"
        ]
        assert liver_candidate and liver_candidate[0]["sources"]

        # 5. 三档方案（真实价格、预算）
        plan_response = client.post(
            "/api/v1/plans",
            json={
                "patient_id": patient_id,
                "analysis_run_id": run["run_id"],
                "budget_limit_cents": 20000,
                "budget_currency": "CNY",
            },
            headers=doctor,
        )
        assert plan_response.status_code == 201, plan_response.text
        plan = plan_response.json()
        assert [tier["tier"] for tier in plan["tiers"]] == ["simplified", "standard", "deep"]
        known = plan["tiers"][0]["cost_summary"]["known_total_cents"]
        assert known is not None and known > 0

        # 6. 编辑 → 审核 → 确认（快照保留）
        edited = client.patch(
            f"/api/v1/plans/{plan['plan_id']}",
            json={"reason": "患者要求不含尿检", "remove_exam_codes": ["URINE_ROUTINE"]},
            headers=doctor,
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["revision_no"] == 2
        assert client.post(
            f"/api/v1/plans/{plan['plan_id']}/submit-review", headers=doctor
        ).status_code == 200
        assert client.post(
            f"/api/v1/plans/{plan['plan_id']}/confirm", headers=doctor
        ).status_code == 200

        # 7. 报告：修订回看 + 中文 PDF + JSON 证据
        report = client.get(f"/api/v1/reports/{plan['plan_id']}?revision_no=1", headers=doctor)
        assert report.status_code == 200
        assert report.json()["revision_no"] == 1
        pdf = client.get(f"/api/v1/reports/{plan['plan_id']}/pdf", headers=doctor)
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF-1.4")
        evidence = client.get(
            f"/api/v1/reports/{plan['plan_id']}/evidence", headers=doctor
        ).json()
        assert evidence["evidence"]["prices"]

        # 8. 依据问答（不修改方案）
        answer = client.post(
            "/api/v1/qa/ask",
            json={
                "patient_id": patient_id,
                "plan_id": plan["plan_id"],
                "question": "为什么推荐肝功能组合？",
            },
            headers=doctor,
        )
        assert answer.status_code == 200, answer.text
        assert answer.json()["citations"]
        assert answer.json()["can_modify_plan"] is False

        # 9. 修订历史可追溯：导入入库与分析都能回溯来源
        revisions = client.get(
            f"/api/v1/profiles/{patient_id}/revisions", headers=doctor
        ).json()
        entity_types = {item["entity_type"] for item in revisions["revisions"]}
        assert {"patient", "health_check", "lab_metric"} <= entity_types
        imported = [item for item in revisions["revisions"] if item["source_kind"] == "import"]
        assert imported and imported[0]["source_ref"].startswith("import_task:")

        # 10. 退出后会话失效
        assert client.post("/api/v1/auth/logout", headers=doctor).json() == {
            "revoked_sessions": 1
        }
        assert client.get("/api/v1/auth/me", headers=doctor).status_code == 401
        assert client.get(f"/api/v1/patients/{patient_id}", headers=doctor).status_code == 401

    # 数据落在真实表里：方案两个修订、记录修订、指标两条。
    assert len(db_session.scalars(select(PlanRevision)).all()) == 2
    assert len(db_session.scalars(select(LabMetric)).all()) == 2
    assert len(db_session.scalars(select(RecordRevision)).all()) >= 3
    assert db_session.scalar(select(Account).where(Account.username == "doctor-a")) is not None


def test_locked_down_chain_requires_login(tmp_path, monkeypatch, test_app, db_session):
    """切换到 AUTH_REQUIRED=true 后：未登录一律 401，登录后完整链路仍可跑通。"""

    from app.core.config import Settings

    monkeypatch.setattr(
        "app.api.dependencies.get_settings",
        lambda: Settings(auth_required=True),
    )
    monkeypatch.setattr(
        "app.services.import_tasks.get_settings",
        lambda: type("S", (), {"import_task_storage_dir": str(tmp_path / "tasks")})(),
    )
    AuthService(db_session, iterations=10_000).create_account(
        username="doctor-a",
        password=DOCTOR_PASSWORD,
        display_name="医生 A",
        role=AccountRole.DOCTOR,
    )
    seed_catalog_and_dictionary(db_session)

    with TestClient(test_app) as client:
        assert client.get("/api/v1/patients").status_code == 401
        assert client.get("/api/v1/workflow/patients").status_code == 401
        assert client.get("/health").status_code == 200  # 探活不需要登录
        token = client.post(
            "/api/v1/auth/login",
            json={"username": "doctor-a", "password": DOCTOR_PASSWORD},
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post(
            "/api/v1/patients",
            json={"anonymous_code": "P-E2E-002", "gender": "female", "birth_date": "1980-05-01"},
            headers=headers,
        )
        assert created.status_code == 201
        upload = client.post(
            "/api/v1/imports/tasks",
            data={"patient_id": created.json()["id"]},
            files={
                "file": (
                    "report.csv",
                    (CSV_HEADER + "2026-01-05,ALT,ALT,88,U/L,0,40\n").encode(),
                    "text/csv",
                )
            },
            headers=headers,
        )
        assert upload.status_code == 201
        assert (
            client.post(
                f"/api/v1/imports/tasks/{upload.json()['task_id']}/confirm",
                json={},
                headers=headers,
            ).status_code
            == 200
        )
        assert client.get("/api/v1/health/detail", headers=headers).status_code == 403
