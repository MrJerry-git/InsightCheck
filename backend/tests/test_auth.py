"""T01：账号、会话、角色与档案访问控制。"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.security import (
    WeakPasswordError,
    hash_password,
    hash_session_token,
    validate_password_strength,
    verify_password,
)
from app.models import Account, AuthSession, Patient
from app.models.enums import AccountRole, Gender
from app.services.auth_service import AuthService, InvalidCredentialsError, utcnow

ADMIN_PASSWORD = "Admin-Pass-2026!"
DOCTOR_PASSWORD = "Doctor-Pass-2026!"
VIEWER_PASSWORD = "Viewer-Pass-2026!"


def make_account(db, username, password, role=AccountRole.DOCTOR, **kwargs):
    return AuthService(db, iterations=10_000).create_account(
        username=username,
        password=password,
        display_name=kwargs.pop("display_name", username),
        role=role,
        **kwargs,
    )


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def force_auth_required(monkeypatch, required: bool = True) -> None:
    monkeypatch.setattr(
        "app.api.dependencies.get_settings",
        lambda: Settings(auth_required=required),
    )


# ---- 口令与令牌基础 -----------------------------------------------------


def test_password_hash_is_salted_and_verifiable():
    digest, salt, iterations = hash_password(ADMIN_PASSWORD, iterations=10_000)
    assert digest != ADMIN_PASSWORD
    assert len(salt) == 32
    assert iterations == 10_000
    assert verify_password(ADMIN_PASSWORD, password_hash=digest, salt=salt, iterations=iterations)
    assert not verify_password(
        "Wrong-Pass-2026!", password_hash=digest, salt=salt, iterations=iterations
    )

    other_digest, other_salt, _ = hash_password(ADMIN_PASSWORD, iterations=10_000)
    assert other_salt != salt
    assert other_digest != digest


@pytest.mark.parametrize(
    "password",
    ["short1!", "aaaaaaaaaaaa", "1234567890123", "密码密码密码密码密码密码"],
)
def test_weak_passwords_are_rejected(password: str):
    with pytest.raises(WeakPasswordError):
        validate_password_strength(password)


def test_session_token_is_stored_as_digest(db_session):
    account = make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    token, session = AuthService(db_session, iterations=10_000).issue_session(account)

    assert session.token_hash == hash_session_token(token)
    assert token not in session.token_hash
    assert db_session.scalar(select(AuthSession).where(AuthSession.token_hash == token)) is None


# ---- 登录 / 退出 / 会话 --------------------------------------------------


def test_login_logout_and_session_lifecycle(test_app, db_session):
    make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    with TestClient(test_app) as client:
        token = login(client, "doctor-a", DOCTOR_PASSWORD)
        me = client.get("/api/v1/auth/me", headers=auth(token))
        assert me.status_code == 200
        assert me.json()["username"] == "doctor-a"
        assert me.json()["role"] == "doctor"

        assert client.post("/api/v1/auth/logout", headers=auth(token)).json() == {
            "revoked_sessions": 1
        }
        expired = client.get("/api/v1/auth/me", headers=auth(token))
        assert expired.status_code == 401


def test_login_rejects_wrong_password_and_unknown_user(test_app, db_session):
    make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    with TestClient(test_app) as client:
        wrong = client.post(
            "/api/v1/auth/login", json={"username": "doctor-a", "password": "Wrong-Pass-2026!"}
        )
        unknown = client.post(
            "/api/v1/auth/login", json={"username": "nobody", "password": DOCTOR_PASSWORD}
        )
        assert wrong.status_code == 401
        assert unknown.status_code == 401
        # 不泄露用户是否存在
        assert wrong.json()["detail"] == unknown.json()["detail"]


def test_inactive_account_cannot_login(test_app, db_session):
    account = make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    AuthService(db_session, iterations=10_000).update_account(account.id, is_active=False)
    with TestClient(test_app) as client:
        response = client.post(
            "/api/v1/auth/login", json={"username": "doctor-a", "password": DOCTOR_PASSWORD}
        )
        assert response.status_code == 403


def test_expired_session_is_rejected(test_app, db_session):
    account = make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    service = AuthService(db_session, iterations=10_000)
    token, _ = service.issue_session(account, ttl=timedelta(seconds=1))
    db_session.query(AuthSession).filter(
        AuthSession.token_hash == hash_session_token(token)
    ).update({"expires_at": utcnow() - timedelta(minutes=1)})
    db_session.commit()

    with TestClient(test_app) as client:
        assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 401


def test_deactivating_account_revokes_sessions(test_app, db_session):
    account = make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    service = AuthService(db_session, iterations=10_000)
    token, _ = service.issue_session(account)
    service.update_account(account.id, is_active=False)

    with TestClient(test_app) as client:
        # 停用即撤销全部会话，旧令牌直接失效；再用该账号登录会被拒绝。
        assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 401
        retry = client.post(
            "/api/v1/auth/login", json={"username": "doctor-a", "password": DOCTOR_PASSWORD}
        )
        assert retry.status_code == 403


def test_password_change_requires_current_password_and_revokes_other_sessions(test_app, db_session):
    make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    with TestClient(test_app) as client:
        first = login(client, "doctor-a", DOCTOR_PASSWORD)
        second = login(client, "doctor-a", DOCTOR_PASSWORD)

        denied = client.post(
            "/api/v1/auth/password",
            headers=auth(first),
            json={"current_password": "Wrong-Pass-2026!", "new_password": "Doctor-Pass-2027!"},
        )
        assert denied.status_code == 401

        changed = client.post(
            "/api/v1/auth/password",
            headers=auth(first),
            json={"current_password": DOCTOR_PASSWORD, "new_password": "Doctor-Pass-2027!"},
        )
        assert changed.status_code == 200
        # 当前会话仍可用，其它会话失效
        assert client.get("/api/v1/auth/me", headers=auth(first)).status_code == 200
        assert client.get("/api/v1/auth/me", headers=auth(second)).status_code == 401
        assert login(client, "doctor-a", "Doctor-Pass-2027!")


# ---- 账号管理（管理员） --------------------------------------------------


def test_only_admin_can_manage_accounts(test_app, db_session):
    make_account(db_session, "admin-a", ADMIN_PASSWORD, role=AccountRole.ADMIN)
    make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    make_account(db_session, "viewer-a", VIEWER_PASSWORD, role=AccountRole.VIEWER)

    with TestClient(test_app) as client:
        admin_token = login(client, "admin-a", ADMIN_PASSWORD)
        doctor_token = login(client, "doctor-a", DOCTOR_PASSWORD)
        viewer_token = login(client, "viewer-a", VIEWER_PASSWORD)

        payload = {
            "username": "doctor-b",
            "password": "Doctor-B-Pass-2026!",
            "display_name": "医生 B",
            "role": "doctor",
        }
        assert (
            client.post(
                "/api/v1/auth/accounts", json=payload, headers=auth(doctor_token)
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/auth/accounts", json=payload, headers=auth(viewer_token)
            ).status_code
            == 403
        )
        created = client.post("/api/v1/auth/accounts", json=payload, headers=auth(admin_token))
        assert created.status_code == 201
        assert created.json()["username"] == "doctor-b"

        # 重复用户名、弱口令、非法用户名
        assert (
            client.post(
                "/api/v1/auth/accounts", json=payload, headers=auth(admin_token)
            ).status_code
            == 409
        )
        weak = {**payload, "username": "doctor-c", "password": "aaaaaaaaaaaaaa"}
        assert (
            client.post("/api/v1/auth/accounts", json=weak, headers=auth(admin_token)).status_code
            == 422
        )
        bad_name = {**payload, "username": "医生C"}
        assert (
            client.post(
                "/api/v1/auth/accounts", json=bad_name, headers=auth(admin_token)
            ).status_code
            == 422
        )

        listing = client.get("/api/v1/auth/accounts", headers=auth(admin_token))
        assert listing.status_code == 200
        assert {item["username"] for item in listing.json()} == {
            "admin-a",
            "doctor-a",
            "viewer-a",
            "doctor-b",
        }
        assert client.get("/api/v1/auth/accounts", headers=auth(doctor_token)).status_code == 403


def test_admin_cannot_lock_itself_out(test_app, db_session):
    admin = make_account(db_session, "admin-a", ADMIN_PASSWORD, role=AccountRole.ADMIN)
    with TestClient(test_app) as client:
        token = login(client, "admin-a", ADMIN_PASSWORD)
        demote = client.patch(
            f"/api/v1/auth/accounts/{admin.id}", json={"role": "viewer"}, headers=auth(token)
        )
        deactivate = client.patch(
            f"/api/v1/auth/accounts/{admin.id}", json={"is_active": False}, headers=auth(token)
        )
        assert demote.status_code == 400
        assert deactivate.status_code == 400


def test_admin_password_reset_revokes_sessions(test_app, db_session):
    make_account(db_session, "admin-a", ADMIN_PASSWORD, role=AccountRole.ADMIN)
    doctor = make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    with TestClient(test_app) as client:
        admin_token = login(client, "admin-a", ADMIN_PASSWORD)
        doctor_token = login(client, "doctor-a", DOCTOR_PASSWORD)
        reset = client.post(
            f"/api/v1/auth/accounts/{doctor.id}/password",
            json={"password": "Doctor-Pass-2027!"},
            headers=auth(admin_token),
        )
        assert reset.status_code == 200
        assert client.get("/api/v1/auth/me", headers=auth(doctor_token)).status_code == 401
        assert login(client, "doctor-a", "Doctor-Pass-2027!")


# ---- 角色权限与档案访问控制 ---------------------------------------------


def test_viewer_is_read_only(test_app, db_session):
    make_account(db_session, "viewer-a", VIEWER_PASSWORD, role=AccountRole.VIEWER)
    make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    with TestClient(test_app) as client:
        viewer_token = login(client, "viewer-a", VIEWER_PASSWORD)
        doctor_token = login(client, "doctor-a", DOCTOR_PASSWORD)

        assert (
            client.get("/api/v1/workflow/patients", headers=auth(viewer_token)).status_code == 200
        )
        assert client.get("/api/v1/patients", headers=auth(viewer_token)).status_code == 200
        blocked = client.post(
            "/api/v1/patients",
            json={"anonymous_code": "P-VIEW-001", "gender": "unknown"},
            headers=auth(viewer_token),
        )
        assert blocked.status_code == 403
        assert (
            client.post(
                "/api/v1/patients",
                json={"anonymous_code": "P-DOC-001", "gender": "unknown"},
                headers=auth(doctor_token),
            ).status_code
            == 201
        )


def test_patient_ownership_blocks_cross_account_access(test_app, db_session):
    make_account(db_session, "admin-a", ADMIN_PASSWORD, role=AccountRole.ADMIN)
    make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    make_account(db_session, "doctor-b", DOCTOR_PASSWORD)
    with TestClient(test_app) as client:
        admin_token = login(client, "admin-a", ADMIN_PASSWORD)
        token_a = login(client, "doctor-a", DOCTOR_PASSWORD)
        token_b = login(client, "doctor-b", DOCTOR_PASSWORD)

        created = client.post(
            "/api/v1/patients",
            json={"anonymous_code": "P-OWNER-001", "gender": "female"},
            headers=auth(token_a),
        )
        assert created.status_code == 201
        patient_id = created.json()["id"]

        assert (
            client.get(f"/api/v1/patients/{patient_id}", headers=auth(token_a)).status_code == 200
        )
        assert (
            client.get(f"/api/v1/patients/{patient_id}", headers=auth(token_b)).status_code == 403
        )
        assert client.get("/api/v1/patients", headers=auth(token_b)).json() == []
        assert len(client.get("/api/v1/patients", headers=auth(admin_token)).json()) == 1
        assert (
            client.get(f"/api/v1/patients/{patient_id}", headers=auth(admin_token)).status_code
            == 200
        )
        # 无权账号读历史与方案也应被拒绝
        assert (
            client.get(f"/api/v1/workflow/patients/{patient_id}", headers=auth(token_b)).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/workflow/records",
                json={
                    "patient_id": patient_id,
                    "check_date": "2026-01-01",
                    "metrics": [{"code": "ALT", "value": 30}],
                },
                headers=auth(token_b),
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/v1/workflow/patients/{patient_id}",
                headers=auth(token_a),
                params={"as_of_date": "2026-12-31"},
            ).status_code
            == 200
        )


def test_unowned_legacy_patient_is_admin_only(test_app, db_session):
    make_account(db_session, "admin-a", ADMIN_PASSWORD, role=AccountRole.ADMIN)
    make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    legacy = Patient(anonymous_code="P-LEGACY-001", gender=Gender.UNKNOWN)
    db_session.add(legacy)
    db_session.commit()

    with TestClient(test_app) as client:
        admin_token = login(client, "admin-a", ADMIN_PASSWORD)
        doctor_token = login(client, "doctor-a", DOCTOR_PASSWORD)
        assert (
            client.get(f"/api/v1/patients/{legacy.id}", headers=auth(doctor_token)).status_code
            == 403
        )
        assert (
            client.get(f"/api/v1/patients/{legacy.id}", headers=auth(admin_token)).status_code
            == 200
        )


def test_auth_required_blocks_anonymous_access(test_app, db_session, monkeypatch):
    make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    with TestClient(test_app) as client:
        assert client.get("/api/v1/workflow/patients").status_code == 200  # 开发模式默认放行
        force_auth_required(monkeypatch)
        assert client.get("/api/v1/workflow/patients").status_code == 401
        assert client.get("/health").status_code == 200  # 健康检查不受鉴权影响
        token = login(client, "doctor-a", DOCTOR_PASSWORD)
        assert client.get("/api/v1/workflow/patients", headers=auth(token)).status_code == 200
        assert (
            client.get("/api/v1/workflow/patients", headers=auth("broken-token")).status_code == 401
        )


def test_authenticate_raises_for_unknown_account(db_session):
    service = AuthService(db_session, iterations=10_000)
    with pytest.raises(InvalidCredentialsError):
        service.authenticate("missing", DOCTOR_PASSWORD)
    account = make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    assert db_session.get(Account, account.id).is_active is True


# ---- 子资源归属过滤与目录类写权限 ---------------------------------------


def test_child_records_are_scoped_to_owner(test_app, db_session):
    """检查记录与指标属于档案：他人账号既看不到列表，也拿不到单条记录。"""

    make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    make_account(db_session, "doctor-b", DOCTOR_PASSWORD)
    with TestClient(test_app) as client:
        token_a = login(client, "doctor-a", DOCTOR_PASSWORD)
        token_b = login(client, "doctor-b", DOCTOR_PASSWORD)
        patient = client.post(
            "/api/v1/patients",
            json={"anonymous_code": "P-SCOPE-001", "gender": "male"},
            headers=auth(token_a),
        ).json()

        created = client.post(
            "/api/v1/health-checks",
            json={"patient_id": patient["id"], "check_date": "2026-01-01"},
            headers=auth(token_a),
        )
        assert created.status_code == 201, created.text
        check_id = created.json()["id"]

        assert client.get("/api/v1/health-checks", headers=auth(token_a)).json() != []
        assert client.get("/api/v1/health-checks", headers=auth(token_b)).json() == []
        # 不可见的子记录统一 404，避免暴露他人档案的存在与结构。
        assert (
            client.get(f"/api/v1/health-checks/{check_id}", headers=auth(token_b)).status_code
            == 404
        )
        # 也不能在他人档案下新增检查记录。
        assert (
            client.post(
                "/api/v1/health-checks",
                json={"patient_id": patient["id"], "check_date": "2026-02-01"},
                headers=auth(token_b),
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/v1/health-checks/{check_id}",
                json={"institution": "他人机构"},
                headers=auth(token_b),
            ).status_code
            == 404
        )


def test_catalog_writes_require_admin(test_app, db_session):
    """体检项目等目录配置只有管理员可写，读权限对医生与只读角色开放。"""

    make_account(db_session, "admin-a", ADMIN_PASSWORD, role=AccountRole.ADMIN)
    make_account(db_session, "doctor-a", DOCTOR_PASSWORD)
    make_account(db_session, "viewer-a", VIEWER_PASSWORD, role=AccountRole.VIEWER)
    payload = {
        "code": "LIVER_US",
        "name": "肝胆胰脾超声",
        "category": "超声",
        "cost_level": "low",
    }
    with TestClient(test_app) as client:
        admin_token = login(client, "admin-a", ADMIN_PASSWORD)
        doctor_token = login(client, "doctor-a", DOCTOR_PASSWORD)
        viewer_token = login(client, "viewer-a", VIEWER_PASSWORD)

        assert (
            client.post("/api/v1/exam-items", json=payload, headers=auth(doctor_token)).status_code
            == 403
        )
        assert (
            client.post("/api/v1/exam-items", json=payload, headers=auth(viewer_token)).status_code
            == 403
        )
        created = client.post("/api/v1/exam-items", json=payload, headers=auth(admin_token))
        assert created.status_code == 201, created.text
        assert client.get("/api/v1/exam-items", headers=auth(viewer_token)).status_code == 200
        assert (
            client.get("/api/v1/metric-dictionaries", headers=auth(doctor_token)).status_code == 200
        )
        assert (
            client.post(
                "/api/v1/metric-dictionaries",
                json={
                    "metric_code": "ALT",
                    "canonical_name": "丙氨酸氨基转移酶",
                    "category": "肝功能",
                    "source": "测试来源",
                    "version": "v1",
                },
                headers=auth(doctor_token),
            ).status_code
            == 403
        )


def test_anonymous_dev_mode_remains_admin(test_app, db_session):
    """未启用鉴权时保持 1.0 行为：匿名调用等同管理员，测试与本地演示不被锁死。"""

    with TestClient(test_app) as client:
        created = client.post(
            "/api/v1/patients", json={"anonymous_code": "P-ANON-001", "gender": "unknown"}
        )
        assert created.status_code == 201
        assert db_session.get(Patient, created.json()["id"]).owner_account_id is None
        assert client.get("/api/v1/patients").json() != []
