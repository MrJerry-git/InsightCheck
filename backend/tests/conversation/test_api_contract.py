"""接口契约与错误码测试：字段、状态、幂等、并发与错误路径。"""

from __future__ import annotations

import httpx

from app.api.routes import conversation as route
from tests.conversation.conftest import BASE, create_profile, send
from tests.conversation.test_conversation_flow import confirmed, visit_2025

STATE_FIELDS = {
    "profile_id", "display_name", "session_id", "version", "draft_version",
    "confirmed_data", "draft", "messages", "pending_actions", "missing", "questions",
    "unknowns", "capabilities", "system_availability", "system_status", "system_history",
    "analysis_stale", "current_snapshot", "service_state",
}


def test_status_reports_model_readiness(client, model):
    ready = client.get(f"{BASE}/status")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert ready.json()["service_state"] == "ready"
    assert ready.json()["model"] == "qwen3-vl:4b-instruct"

    model.ready = False
    offline = client.get(f"{BASE}/status").json()
    assert offline["ready"] is False
    assert offline["service_state"] == "model_unavailable"
    assert offline["message"]

    model.ready = True
    model.error = httpx.ConnectError("down")
    assert client.get(f"{BASE}/status").json()["ready"] is False


def test_state_contract_fields(client, model):
    profile = create_profile(client, "c1")
    state = client.get(f"{BASE}/profiles/{profile['profile_id']}/state").json()
    assert STATE_FIELDS <= set(state)
    assert state["version"] == 0 and state["draft_version"] == 0
    assert state["confirmed_data"] is None and state["draft"] is None
    assert state["messages"] == [] and state["pending_actions"] == []
    assert state["missing"] == [] and state["questions"] == []
    assert state["analysis_stale"] is False
    assert state["service_state"] == "ready"
    assert set(state["system_availability"]) == {"cardiovascular", "glucose_metabolism",
                                                "renal"}


def test_message_contract_fields(client, model):
    profile, _ = confirmed(client, model, [visit_2025()], prefix="c2")
    body = send(client, profile["profile_id"], "收缩压改成 132 mmHg", "c2-msg")
    assert STATE_FIELDS <= set(body)
    assert {"message_id", "user_message_id", "reply", "changed_summary",
            "rejected_actions"} <= set(body)
    assert isinstance(body["reply"], str) and body["reply"]
    assert body["changed_summary"][0]["action"] == "update_visit"
    assert body["changed_summary"][0]["scope"] == "confirmed"
    assert body["messages"][-1]["role"] == "assistant"
    assert body["messages"][-1]["changed_summary"] == body["changed_summary"]


def test_unknown_profile_returns_404(client, model):
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"{BASE}/profiles/{missing}/state").status_code == 404
    assert client.post(f"{BASE}/profiles/{missing}/confirm",
                       json={"op_id": "x", "expected_draft_version": 0}).status_code == 404
    assert client.post(f"{BASE}/profiles/{missing}/plan",
                       json={"op_id": "x"}).status_code == 404
    assert client.get(f"{BASE}/profiles/{missing}/plans").status_code == 404
    assert client.post(f"{BASE}/profiles/{missing}/messages",
                       json={"op_id": "x", "text": "你好"}).status_code == 404
    error = client.get(f"{BASE}/profiles/{missing}/state").json()
    assert error["error"] == "not_found" and error["detail"]


def test_missing_op_id_is_invalid_input(client, model):
    profile = create_profile(client, "c3")
    assert client.post(f"{BASE}/profiles/{profile['profile_id']}/messages",
                       json={"text": "你好"}).status_code == 422
    assert client.post(f"{BASE}/profiles/{profile['profile_id']}/confirm",
                       json={}).status_code == 422
    assert client.post(f"{BASE}/profiles", json={}).status_code == 422
    assert client.post(f"{BASE}/profiles/{profile['profile_id']}/messages",
                       json={"op_id": "c3-msg", "text": "x",
                             "unknown": 1}).status_code == 422


def test_busy_returns_429_without_writing(client, model):
    profile = create_profile(client, "c4")
    route.lock.acquire()
    try:
        response = client.post(f"{BASE}/profiles/{profile['profile_id']}/messages",
                               json={"op_id": "c4-msg", "text": "你好"})
        assert response.status_code == 429
        assert response.json()["error"] == "processing"
    finally:
        route.lock.release()
    state = client.get(f"{BASE}/profiles/{profile['profile_id']}/state").json()
    assert state["messages"] == []
    assert state["draft"] is None


def test_model_error_maps_to_business_status(client, model):
    profile = create_profile(client, "c5")
    model.error = httpx.ConnectError("offline")
    response = client.post(f"{BASE}/profiles/{profile['profile_id']}/messages",
                           json={"op_id": "c5-msg", "text": "2025-09-20 体检：血压 138"})
    assert response.status_code == 503
    assert response.json()["error"] == "model_unavailable"
    model.error = httpx.ReadTimeout("slow")
    timeout = client.post(f"{BASE}/profiles/{profile['profile_id']}/messages",
                          json={"op_id": "c5-timeout", "text": "2025-09-20 体检：血压 138"})
    assert timeout.status_code == 504
    assert timeout.json()["error"] == "timeout"
    model.error = None
    model.extraction = {
        "sex": "male", "known_cvd": False, "pregnant": False, "symptomatic": False,
        "visits": [{"date": "2025-09-20", "sbp": 138}],
        "evidence": [{"path": "visits.0.date", "quote": "2025-09-20"},
                     {"path": "visits.0.sbp", "quote": "血压 138"}],
        "warnings": []}
    # 失败不产生半完成写入，也不影响后续请求。
    ok = send(client, profile["profile_id"], "2025-09-20 体检：血压 138", "c5-ok")
    assert ok["draft"] is not None
    assert ok["draft"]["visits"][0]["sbp"] == 138


def test_validation_failure_keeps_draft(client, model):
    profile, _ = confirmed(client, model, [visit_2025()], prefix="c6")
    text = "检查日期：2025-10-10\n年龄：55 岁\n收缩压 138 mmHg"
    model.extraction = {
        "sex": "male", "known_cvd": False, "pregnant": False, "symptomatic": False,
        "visits": [{"date": "2025-10-10", "age": 55, "sbp": 138}],
        "evidence": [{"path": "visits.0.date", "quote": "检查日期：2025-10-10"},
                     {"path": "visits.0.age", "quote": "年龄：55 岁"},
                     {"path": "visits.0.sbp", "quote": "收缩压 138 mmHg"}],
        "warnings": []}
    send(client, profile["profile_id"], text, "c6-draft")
    draft_state = client.get(f"{BASE}/profiles/{profile['profile_id']}/state").json()
    assert draft_state["missing"], draft_state
    failed = client.post(
        f"{BASE}/profiles/{profile['profile_id']}/confirm",
        json={"op_id": "c6-confirm-partial",
              "expected_draft_version": draft_state["draft_version"]})
    assert failed.status_code == 422
    body = failed.json()
    assert body["error"] == "validation_failed"
    assert body["errors"]
    assert body["missing"]
    state = client.get(f"{BASE}/profiles/{profile['profile_id']}/state").json()
    assert state["version"] == 1
    assert state["draft"] is not None
    assert len(state["confirmed_data"]["visits"]) == 1


def test_snapshot_read_only_and_not_found(client, model):
    profile, _ = confirmed(client, model, [visit_2025()], prefix="c7")
    plan = client.post(f"{BASE}/profiles/{profile['profile_id']}/plan",
                       json={"op_id": "c7-plan"}).json()
    view = client.get(f"{BASE}/profiles/{profile['profile_id']}"
                      f"/plans/{plan['snapshot_id']}").json()
    assert view["read_only"] is True
    assert view["is_latest_version"] is True
    assert view["current_version"] == 1
    assert view["recommendations"] and view["overall"] and view["scope_index"]
    assert view["sources"] and view["limitations"]
    other = create_profile(client, "c7b")
    assert client.get(f"{BASE}/profiles/{other['profile_id']}"
                      f"/plans/{plan['snapshot_id']}").status_code == 404
    assert client.get(f"{BASE}/profiles/{profile['profile_id']}"
                      "/plans/none").status_code == 404


def test_plan_is_idempotent_and_version_checked(client, model):
    profile, _ = confirmed(client, model, [visit_2025()], prefix="c8")
    first = client.post(f"{BASE}/profiles/{profile['profile_id']}/plan",
                        json={"op_id": "c8-plan", "expected_version": 1})
    second = client.post(f"{BASE}/profiles/{profile['profile_id']}/plan",
                         json={"op_id": "c8-plan", "expected_version": 1})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()
    assert len(client.get(f"{BASE}/profiles/{profile['profile_id']}/plans").json()) == 1

    conflict = client.post(f"{BASE}/profiles/{profile['profile_id']}/plan",
                           json={"op_id": "c8-plan-2", "expected_version": 0})
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "version_conflict"
    assert conflict.json()["current_version"] == 1


def test_profiles_list_reports_workspace_identity(client, model):
    first = create_profile(client, "c9a")
    second = client.post(f"{BASE}/profiles",
                         json={"op_id": "c9b", "display_name": "第二位体检人"}).json()
    listing = client.get(f"{BASE}/profiles").json()
    by_id = {item["profile_id"]: item for item in listing}
    assert by_id[first["profile_id"]]["display_name"] == first["display_name"]
    assert by_id[second["profile_id"]]["display_name"] == "第二位体检人"
    assert by_id[second["profile_id"]]["has_confirmed"] is False
    assert by_id[first["profile_id"]]["created_at"]
