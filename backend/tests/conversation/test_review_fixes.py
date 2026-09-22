"""AI-T01—AI-T08 审核复核：草稿版本、会话绑定与账号归属。

对应用户/审核指出的问题：
* confirm 只检查已确认版本，旧确认请求仍能确认被改过的新草稿；
* 消息/重置未绑定会话，旧会话迟到写入会污染新会话；
* 对话路由没有账号鉴权与归属过滤，T01 启用权限后不兼容。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.models.enums import AccountRole
from app.services.auth_service import AuthService
from tests.conversation.conftest import BASE, create_profile, make_report, send
from tests.conversation.test_conversation_flow import visit_2025

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


def draft_profile(client, model, prefix: str):
    profile = create_profile(client, f"{prefix}-create")
    text, extraction = make_report([visit_2025()])
    model.extraction = extraction
    state = send(client, profile["profile_id"], text, f"{prefix}-draft")
    return profile, state


def test_confirm_must_match_current_draft_version(client, model):
    """审核 P1：用户看到的草稿被别人改过后，旧确认请求必须 409。"""

    profile, first = draft_profile(client, model, "rv")
    assert first["draft_version"] >= 1
    stale_version = first["draft_version"]

    updated_text, updated = make_report(
        [visit_2025() | {"fasting_glucose": 6.8, "glucose_status": "diabetes"}]
    )
    model.extraction = updated
    second = send(client, profile["profile_id"], updated_text, "rv-draft-2")
    assert second["draft_version"] > stale_version

    stale = client.post(
        f"{BASE}/profiles/{profile['profile_id']}/confirm",
        json={"op_id": "rv-confirm-stale", "expected_draft_version": stale_version},
    )
    assert stale.status_code == 409, stale.text
    body = stale.json()
    assert body["error"] == "version_conflict"
    assert body["current_draft_version"] == second["draft_version"]
    assert "重新核对" in body["detail"]
    state = client.get(f"{BASE}/profiles/{profile['profile_id']}/state").json()
    assert state["confirmed_data"] is None

    fresh = client.post(
        f"{BASE}/profiles/{profile['profile_id']}/confirm",
        json={
            "op_id": "rv-confirm-fresh",
            "expected_draft_version": second["draft_version"],
        },
    )
    assert fresh.status_code == 200, fresh.text
    # 确认入库的是用户复核过的那一版草稿内容，而不是更早的一版。
    current_value = second["draft"]["visits"][0]["fasting_glucose"]
    assert fresh.json()["confirmed_data"]["visits"][0]["fasting_glucose"] == current_value


def test_confirm_requires_expected_draft_version(client, model):
    """expected_draft_version 是必填字段，不能省略后再靠服务端猜。"""

    profile, _ = draft_profile(client, model, "rq")
    missing = client.post(
        f"{BASE}/profiles/{profile['profile_id']}/confirm", json={"op_id": "rq-confirm"}
    )
    assert missing.status_code == 422
    assert any(
        error["loc"][-1] == "expected_draft_version" for error in missing.json()["detail"]
    )


def test_old_session_cannot_write_after_restart(client, model):
    """审核 P1：会话被替换后，旧会话的迟到消息必须 409，不写入新会话。"""

    profile, state = draft_profile(client, model, "rs")
    old_session = state["session_id"]

    restarted = client.post(
        f"{BASE}/profiles/{profile['profile_id']}/restart",
        json={"op_id": "rs-restart", "session_id": old_session},
    )
    assert restarted.status_code == 200, restarted.text
    new_session = restarted.json()["session_id"]
    assert new_session != old_session

    late = client.post(
        f"{BASE}/profiles/{profile['profile_id']}/messages",
        json={"op_id": "rs-late", "text": "补充：年龄 61 岁", "session_id": old_session},
    )
    assert late.status_code == 409, late.text
    assert late.json()["current_session_id"] == new_session
    fresh = client.get(f"{BASE}/profiles/{profile['profile_id']}/state").json()
    assert fresh["session_id"] == new_session
    assert all("迟到" not in item["text"] for item in fresh["messages"])


def test_profiles_are_scoped_to_owner_account(test_app, db_session, model):
    """审核 P1/集成：对话档案按账号归属隔离，跨账号读写都返回 404。"""

    make_account(db_session, "conv-a")
    make_account(db_session, "conv-b")
    with TestClient(test_app) as client:
        headers_owner = login(client, "conv-a")
        headers_other = login(client, "conv-b")

        created = client.post(
            f"{BASE}/profiles", json={"op_id": "own-1"}, headers=headers_owner
        )
        assert created.status_code == 201, created.text
        profile_id = created.json()["profile_id"]

        owner_list = client.get(f"{BASE}/profiles", headers=headers_owner).json()
        assert [item["profile_id"] for item in owner_list] == [profile_id]
        assert client.get(f"{BASE}/profiles", headers=headers_other).json() == []

        assert (
            client.get(
                f"{BASE}/profiles/{profile_id}/state", headers=headers_other
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"{BASE}/profiles/{profile_id}/messages",
                json={"op_id": "own-msg", "text": "你好"},
                headers=headers_other,
            ).status_code
            == 404
        )


def test_conversation_routes_require_token_when_auth_required(monkeypatch, test_app):
    """T01 集成：启用鉴权后，对话接口对匿名请求返回 401。"""

    monkeypatch.setattr(
        "app.api.dependencies.get_settings", lambda: Settings(auth_required=True)
    )
    with TestClient(test_app) as client:
        assert client.get(f"{BASE}/status").status_code == 401
        assert client.get(f"{BASE}/profiles").status_code == 401
        assert client.post(f"{BASE}/profiles", json={"op_id": "anon"}).status_code == 401
        assert client.get(f"{BASE}/profiles/whatever/state").status_code == 401
