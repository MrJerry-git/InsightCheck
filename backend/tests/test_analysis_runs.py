"""T04/T05：分析编排、结果保存与跨系统候选汇总。"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    AnalysisRun,
    ExamItem,
    HealthCheck,
    ImagingExam,
    LabMetric,
    Lesion,
    MetricDictionary,
    Patient,
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
        "CHEST_CT": ("胸部 CT", "影像检查", True, CostLevel.HIGH),
        "LIVER_FUNCTION_PANEL": ("肝功能组合", "实验室检查", False, CostLevel.LOW),
        "LIPID_PANEL": ("血脂组合", "实验室检查", False, CostLevel.LOW),
        "URINE_ROUTINE": ("尿常规", "实验室检查", False, CostLevel.LOW),
    }
    created = {}
    for code, (name, category, radiation, cost) in items.items():
        item = ExamItem(
            code=code,
            name=name,
            category=category,
            radiation=radiation,
            cost_level=cost,
        )
        db.add(item)
        created[code] = item
    db.commit()
    return created


def seed_dictionary(db, code, name, category="肝肾功能及生化", unit="U/L"):
    definition = MetricDictionary(
        metric_code=code,
        canonical_name=name,
        aliases=[],
        standard_unit=unit,
        category=category,
        value_type=ValueType.NUMERIC,
        unit_conversions={},
        source="测试来源",
        version="v1",
    )
    db.add(definition)
    db.commit()
    return definition


def seed_patient(db, code="P-ANA-001", birth_date=date(1975, 3, 1), owner=None):
    patient = Patient(
        anonymous_code=code,
        gender=Gender.MALE,
        birth_date=birth_date,
        height=172.0,
        owner_account_id=None if owner is None else owner.id,
    )
    db.add(patient)
    db.commit()
    return patient


def seed_abnormal_liver(db, patient):
    check = HealthCheck(
        patient_id=patient.id, check_date=date(2026, 1, 5), source_kind="import"
    )
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
            original_unit="U/L",
            standard_unit="U/L",
            reference_min=0.0,
            reference_max=40.0,
            status=MetricStatus.HIGH,
            normalization_status="normalized",
            normalization_version="v1",
        )
    )
    db.commit()
    return check


def seed_lung_lesion(db, patient):
    check = db.scalar(
        select(HealthCheck).where(HealthCheck.patient_id == patient.id).limit(1)
    )
    exam = ImagingExam(
        health_check_id=check.id,
        exam_type="CT",
        body_part="胸部",
        report_text="右肺上叶结节，较前相仿",
        exam_date=date(2026, 1, 5),
    )
    db.add(exam)
    db.flush()
    db.add(
        Lesion(
            imaging_exam_id=exam.id,
            lesion_type="肺结节",
            original_location="右肺上叶",
            location="右肺上叶",
            size_mm=4.4,
        )
    )
    db.commit()
    return exam


def test_analysis_deduplicates_cross_system_candidates(test_app, db_session):
    doctor = make_account(db_session, "doctor-a")
    seed_catalog(db_session)
    seed_dictionary(db_session, "ALT", "丙氨酸氨基转移酶")
    seed_dictionary(db_session, "LIVER_FUNCTION_PANEL", "肝功能组合", category="实验室检查")
    patient = seed_patient(db_session, owner=doctor)
    seed_abnormal_liver(db_session, patient)
    seed_lung_lesion(db_session, patient)

    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        response = client.post(
            "/api/v1/analyses",
            json={"patient_id": patient.id, "as_of_date": "2026-02-01"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["stale"] is False

        findings = {item["finding_code"] for item in payload["findings"]}
        assert "LIVER_ENZYME_ABNORMAL" in findings
        assert "LUNG_NODULE" in findings
        assert payload["summary"]["finding_count"] == len(payload["findings"])

        # 跨系统去重：同一检查项目在候选中只出现一次，理由合并保留。
        liver = [item for item in payload["candidates"] if item["code"] == "LIVER_FUNCTION_PANEL"]
        assert len(liver) == 1
        assert liver[0]["sources"][0]["finding_code"] == "LIVER_ENZYME_ABNORMAL"
        assert liver[0]["sources"][0]["evidence_refs"]

        chest = [item for item in payload["candidates"] if item["code"] == "CHEST_CT"]
        assert len(chest) == 1
        assert chest[0]["sources"][0]["finding_code"] == "LUNG_NODULE"
        assert chest[0]["radiation"] is True

        # 未被任何发现指向的项目仍作为目录基线列出，但明确标注需人工确认。
        urine = [item for item in payload["candidates"] if item["code"] == "URINE_ROUTINE"][0]
        assert urine["decision"] == "require_review"
        assert urine["rule_status"] == "NOT_CONFIGURED"
        assert urine["score"] is None
        assert "未评估" in urine["model_status"]
        assert any("人工确认" in note for note in urine["missing_information"])
        # 结果自带免责与来源说明，不与医学结论混淆。
        assert any("待复核" in note for note in payload["notes"])


def test_unmapped_finding_is_reported_not_dropped(test_app, db_session):
    doctor = make_account(db_session, "doctor-a")
    seed_catalog(db_session)
    seed_dictionary(db_session, "CRP", "C反应蛋白", category="感染筛查")
    patient = seed_patient(db_session, owner=doctor)
    check = HealthCheck(patient_id=patient.id, check_date=date(2026, 1, 5))
    db_session.add(check)
    db_session.flush()
    db_session.add(
        LabMetric(
            health_check_id=check.id,
            metric_code="CRP",
            original_name="CRP",
            canonical_name="C反应蛋白",
            original_value="9.9",
            value=9.9,
            status=MetricStatus.HIGH,
            normalization_status="normalized",
            normalization_version="v1",
        )
    )
    db_session.commit()

    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        payload = client.post(
            "/api/v1/analyses",
            json={"patient_id": patient.id, "as_of_date": "2026-02-01"},
            headers=headers,
        ).json()
        unmapped = [item for item in payload["findings"] if item["finding_code"] == "CRP_HIGH"]
        assert unmapped and unmapped[0]["mapped"] is False
        assert payload["summary"]["unmapped_finding_count"] == 1
        # 未登记映射的发现如实记录在说明里，不静默生成候选。
        assert any("未登记映射" in note for note in payload["notes"])
        assert payload["stale"] is False


def test_result_marks_stale_after_data_changes(test_app, db_session):
    doctor = make_account(db_session, "doctor-a")
    seed_catalog(db_session)
    seed_dictionary(db_session, "ALT", "丙氨酸氨基转移酶")
    patient = seed_patient(db_session, owner=doctor)
    check = seed_abnormal_liver(db_session, patient)

    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        run = client.post(
            "/api/v1/analyses",
            json={"patient_id": patient.id, "as_of_date": "2026-02-01"},
            headers=headers,
        ).json()
        assert run["stale"] is False

        metric = db_session.scalar(select(LabMetric))
        metric.value = 120.0
        metric.original_value = "120"
        db_session.commit()

        refreshed = client.get(f"/api/v1/analyses/{run['run_id']}", headers=headers).json()
        assert refreshed["stale"] is True
        assert "重新分析" in refreshed["stale_reason"]
        # 旧结果保持原样，不被新数据覆盖。
        assert refreshed["input_fingerprint"] == run["input_fingerprint"]
        assert refreshed["candidates"] == run["candidates"]

        listing = client.get(
            f"/api/v1/analyses?patient_id={patient.id}", headers=headers
        ).json()
        assert listing[0]["stale"] is True
        assert db_session.get(HealthCheck, check.id) is not None


def test_analysis_fixed_decision_date_excludes_later_records(test_app, db_session):
    doctor = make_account(db_session, "doctor-a")
    seed_catalog(db_session)
    seed_dictionary(db_session, "ALT", "丙氨酸氨基转移酶")
    patient = seed_patient(db_session, owner=doctor)
    seed_abnormal_liver(db_session, patient)
    later = HealthCheck(patient_id=patient.id, check_date=date(2026, 6, 1))
    db_session.add(later)
    db_session.flush()
    db_session.add(
        LabMetric(
            health_check_id=later.id,
            metric_code="ALT",
            original_name="ALT",
            canonical_name="丙氨酸氨基转移酶",
            original_value="20",
            value=20.0,
            reference_min=0.0,
            reference_max=40.0,
            status=MetricStatus.NORMAL,
            normalization_status="normalized",
            normalization_version="v1",
        )
    )
    db_session.commit()

    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        early = client.post(
            "/api/v1/analyses",
            json={"patient_id": patient.id, "as_of_date": "2026-02-01"},
            headers=headers,
        ).json()
        assert early["as_of_date"] == "2026-02-01"
        assert any(
            item["finding_code"] == "LIVER_ENZYME_ABNORMAL" for item in early["findings"]
        )
        late = client.post(
            "/api/v1/analyses",
            json={"patient_id": patient.id, "as_of_date": "2026-07-01"},
            headers=headers,
        ).json()
        assert late["findings"] == []
        assert late["summary"]["finding_count"] == 0


def test_analysis_validation_and_permissions(test_app, db_session):
    doctor = make_account(db_session, "doctor-a")
    make_account(db_session, "doctor-b")
    seed_catalog(db_session)
    patient = seed_patient(db_session, owner=doctor)

    with TestClient(test_app) as client:
        headers_a = login(client, "doctor-a")
        headers_b = login(client, "doctor-b")
        future = client.post(
            "/api/v1/analyses",
            json={"patient_id": patient.id, "as_of_date": "2999-01-01"},
            headers=headers_a,
        )
        assert future.status_code == 422
        assert (
            client.post(
                "/api/v1/analyses",
                json={"patient_id": patient.id, "as_of_date": "2026-02-01"},
                headers=headers_b,
            ).status_code
            == 403
        )
        run = client.post(
            "/api/v1/analyses",
            json={"patient_id": patient.id, "as_of_date": "2026-02-01", "request_id": "ana-1"},
            headers=headers_a,
        ).json()
        assert client.get(f"/api/v1/analyses/{run['run_id']}", headers=headers_b).status_code == 403
        # request_id 幂等：同一请求不重复生成运行。
        again = client.post(
            "/api/v1/analyses",
            json={"patient_id": patient.id, "as_of_date": "2026-02-01", "request_id": "ana-1"},
            headers=headers_a,
        ).json()
        assert again["run_id"] == run["run_id"]
        assert len(db_session.scalars(select(AnalysisRun)).all()) == 1


def test_finding_map_endpoint_marks_unreviewed(test_app, db_session):
    make_account(db_session, "doctor-a")
    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        response = client.get("/api/v1/analyses/finding-map", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["reviewed"] is False
        assert body["version"]
        assert any(entry["finding_code"] == "LIVER_ENZYME_ABNORMAL" for entry in body["entries"])


def test_finding_map_configuration_is_shipped_with_the_code():
    """审核 P1：干净检出后 /analyses 必须能加载映射配置，不能依赖开发机文件。"""

    from app.services.analysis.finding_map import MAP_PATH, load_finding_map

    assert MAP_PATH.exists(), f"缺少已提交的映射配置：{MAP_PATH}"
    assert MAP_PATH.parent.name == "data"
    mapping = load_finding_map()
    assert mapping.version
    liver = mapping.rule("LIVER_ENZYME_ABNORMAL")
    assert liver is not None and liver.exam_codes == ("LIVER_FUNCTION_PANEL",)
    lung = mapping.rule("LUNG_NODULE")
    assert lung is not None and "结节" in lung.lesion_keywords


def test_patient_context_change_marks_analysis_stale(test_app, db_session):
    """审核 P1：性别/出生日期影响适用规则，改了患者字段旧分析必须过期。"""

    doctor = make_account(db_session, "doctor-a")
    seed_catalog(db_session)
    seed_dictionary(db_session, "ALT", "丙氨酸氨基转移酶")
    patient = seed_patient(db_session, owner=doctor)
    seed_abnormal_liver(db_session, patient)

    with TestClient(test_app) as client:
        headers = login(client, "doctor-a")
        run = client.post(
            "/api/v1/analyses",
            json={"patient_id": patient.id, "as_of_date": "2026-02-01"},
            headers=headers,
        ).json()
        assert run["stale"] is False

        patient.gender = Gender.FEMALE
        patient.birth_date = date(1960, 5, 1)
        db_session.commit()

        refreshed = client.get(f"/api/v1/analyses/{run['run_id']}", headers=headers).json()
        assert refreshed["stale"] is True
        assert "重新分析" in refreshed["stale_reason"]
        # 旧结果按原版本回看，不被患者字段修改改写。
        assert refreshed["findings"] == run["findings"]
        assert refreshed["input_fingerprint"] == run["input_fingerprint"]
