"""任务书验收 15–19：新建用户档案、工作区切换与档案隔离。"""

from __future__ import annotations

from app.services.conversation import plans as PL
from tests.conversation.conftest import BASE, make_report, send
from tests.conversation.test_conversation_flow import (
    PROFILE,
    confirmed,
    upload,
    visit_2024,
    visit_2025,
)


def new_profile(client, op_id: str, *, save: str = "no", profile_id: str | None = None,
                display_name: str | None = None):
    body = {"op_id": op_id, "display_name": display_name,
            "save_current": {"profile_id": profile_id, "save": save}}
    return client.post(f"{BASE}/profiles", json=body)


def plan(client, profile_id: str, op_id: str, expected_version: int | None = None):
    body = {"op_id": op_id}
    if expected_version is not None:
        body["expected_version"] = expected_version
    return client.post(f"{BASE}/profiles/{profile_id}/plan", json=body)


# ---------------------------------------------------------------- 验收 15


def test_new_profile_clears_workspace_and_keeps_old_snapshots(client, model):
    """验收 15：先保存旧规划再新建；当前资料/对话/草稿清空，旧快照仍可回看。"""
    old, _ = confirmed(client, model, [visit_2025()], prefix="A")
    upload(client, model, old["profile_id"], "A-draft", [visit_2024()])
    saved = plan(client, old["profile_id"], "A-plan", expected_version=1)
    assert saved.status_code == 200, saved.text
    snapshot_id = saved.json()["snapshot_id"]

    created = new_profile(client, "B-new", save="yes", profile_id=old["profile_id"],
                          display_name="第二位体检人")
    assert created.status_code == 201, created.text
    fresh = created.json()
    assert fresh["profile_id"] != old["profile_id"]
    assert fresh["session_id"]
    assert fresh["display_name"] == "第二位体检人"
    assert fresh["version"] == 0
    assert fresh["confirmed_data"] is None
    assert fresh["draft"] is None
    assert fresh["messages"] == []
    assert fresh["pending_actions"] == []
    assert fresh["unknowns"] == []
    assert fresh["analysis_stale"] is False
    assert fresh["system_availability"] == {
        "cardiovascular": False, "glucose_metabolism": False, "renal": False}
    assert all(item["calculable"] is False for item in fresh["system_status"].values())
    assert fresh["current_snapshot"] is None

    # 旧档案的已保存资料与快照保持原样，可按档案只读回看。
    old_state = client.get(f"{BASE}/profiles/{old['profile_id']}/state").json()
    assert len(old_state["confirmed_data"]["visits"]) == 1
    snapshot = client.get(
        f"{BASE}/profiles/{old['profile_id']}/plans/{snapshot_id}").json()
    assert snapshot["profile_id"] == old["profile_id"]
    assert snapshot["display_name"] == old["display_name"]
    assert snapshot["read_only"] is True
    listing = client.get(f"{BASE}/profiles").json()
    assert {item["display_name"] for item in listing} == {old["display_name"],
                                                         "第二位体检人"}


def test_new_profile_keeps_old_plan_when_saving(client, model):
    """验收 15：选择先保存时旧规划真的被保存（生成快照）。"""
    old, _ = confirmed(client, model, [visit_2025()], prefix="C")
    assert client.get(f"{BASE}/profiles/{old['profile_id']}/plans").json() == []
    new_profile(client, "C-new", save="yes", profile_id=old["profile_id"])
    plans = client.get(f"{BASE}/profiles/{old['profile_id']}/plans").json()
    assert len(plans) == 1
    assert plans[0]["status"] == "current"
    assert plans[0]["snapshot_version"] == 1


# ---------------------------------------------------------------- 验收 16


def test_cancel_keeps_everything(client, model):
    """验收 16：提示中取消时原状态完全保留，不新建档案。"""
    old, _ = confirmed(client, model, [visit_2025()], prefix="D")
    upload(client, model, old["profile_id"], "D-draft", [visit_2024()])
    before = client.get(f"{BASE}/profiles/{old['profile_id']}/state").json()
    cancelled = new_profile(client, "D-new", save="cancel", profile_id=old["profile_id"])
    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled"] is True
    assert cancelled.json()["created"] is False
    after = client.get(f"{BASE}/profiles/{old['profile_id']}/state").json()
    assert after["profile_id"] == before["profile_id"]
    assert after["draft"] == before["draft"]
    assert after["confirmed_data"] == before["confirmed_data"]
    assert len(client.get(f"{BASE}/profiles").json()) == 1


def test_save_failure_does_not_switch(client, model, monkeypatch):
    """验收 16：选择先保存但保存失败时不切换，旧工作区保持不变。"""
    old, _ = confirmed(client, model, [visit_2025()], prefix="E")

    def boom(*_args, **_kwargs):
        raise RuntimeError("snapshot storage unavailable")

    monkeypatch.setattr(PL, "generate_snapshot", boom)
    failed = new_profile(client, "E-new", save="yes", profile_id=old["profile_id"])
    assert failed.status_code == 400
    assert failed.json()["error"] == "save_failed"
    monkeypatch.undo()
    state = client.get(f"{BASE}/profiles/{old['profile_id']}/state").json()
    assert state["profile_id"] == old["profile_id"]
    assert len(state["confirmed_data"]["visits"]) == 1
    assert len(client.get(f"{BASE}/profiles").json()) == 1
    assert client.get(f"{BASE}/profiles/{old['profile_id']}/plans").json() == []


def test_skip_saving_only_drops_unsaved_workspace(client, model):
    """验收 16：明确不保存继续时只放弃未保存工作区，不删除旧快照。"""
    old, _ = confirmed(client, model, [visit_2025()], prefix="F")
    plan(client, old["profile_id"], "F-plan", expected_version=1)
    upload(client, model, old["profile_id"], "F-draft", [visit_2024()])
    created = new_profile(client, "F-new", save="no", profile_id=old["profile_id"])
    assert created.status_code == 201
    plans = client.get(f"{BASE}/profiles/{old['profile_id']}/plans").json()
    assert len(plans) == 1
    old_state = client.get(f"{BASE}/profiles/{old['profile_id']}/state").json()
    assert len(old_state["confirmed_data"]["visits"]) == 1
    assert old_state["draft"] is not None


# ---------------------------------------------------------------- 验收 17


def test_two_people_do_not_inherit_data(client, model):
    """验收 17：两名不同仿真人连续导入，新档案不继承旧人的任何内容。"""
    first, _ = confirmed(client, model, [visit_2025()], prefix="G")
    second = new_profile(client, "H-new", save="yes",
                         profile_id=first["profile_id"]).json()
    pid = second["profile_id"]
    assert second["confirmed_data"] is None

    other_text, other_result = make_report(
        [visit_2024(date="2026-03-05", age=41, sbp=118, total_c=4.6, hdl_c=1.5, bmi=22,
                    egfr=101, dm=False, smoking=False, bp_tx=False, statin=False,
                    fasting_glucose=4.9)],
        profile={"sex": "female", "known_cvd": False, "pregnant": False,
                 "symptomatic": False})
    model.extraction = other_result
    body = send(client, pid, other_text, "H-upload")
    assert body["missing"] == []
    assert body["confirmed_data"] is None  # 未确认前不进入历史
    done = client.post(f"{BASE}/profiles/{pid}/confirm",
                       json={"op_id": "H-confirm", "expected_version": 0}).json()
    assert done["profile_id"] == pid
    assert len(done["confirmed_data"]["visits"]) == 1
    assert done["confirmed_data"]["sex"] == "female"
    assert done["confirmed_data"]["visits"][0]["sbp"] == 118
    assert done["system_status"]["cardiovascular"]["has_data"] is True
    assert done["analysis_stale"] is False
    # 刷新后仍是新档案；旧档案的规划不能在新档案上打开。
    after = client.get(f"{BASE}/profiles/{pid}/state").json()
    assert after["confirmed_data"]["visits"][0]["sbp"] == 118
    assert after["confirmed_data"]["visits"][0]["date"] == "2026-03-05"
    old_plan = plan(client, first["profile_id"], "G-plan", expected_version=1).json()
    lookup = client.get(f"{BASE}/profiles/{pid}/plans/{old_plan['snapshot_id']}")
    assert lookup.status_code == 404
    assert client.get(f"{BASE}/profiles/{pid}/state").json()["confirmed_data"] == \
        after["confirmed_data"]


def test_three_records_of_one_person_stay_in_one_profile(client, model):
    """验收 17：参赛资料包 A（同一人三年）属于同一档案。"""
    _, body = confirmed(
        client, model,
        [visit_2024(date="2023-09-10", age=53, sbp=132, total_c=4.9, hdl_c=1.4, bmi=25.1,
                    egfr=95, fasting_glucose=5.2),
         visit_2024(date="2024-09-15", age=54),
         visit_2025(date="2025-09-20", age=55)],
        prefix="I")
    visits = body["confirmed_data"]["visits"]
    assert [item["date"] for item in visits] == ["2023-09-10", "2024-09-15", "2025-09-20"]
    assert len({item["record_id"] for item in visits}) == 3


# ---------------------------------------------------------------- 验收 18


def test_late_response_of_old_profile_does_not_touch_new(client, model):
    """验收 18：切换时旧请求只能作用于原档案，迟到响应不污染新档案。"""
    old, _ = confirmed(client, model, [visit_2025()], prefix="J")
    old_state = client.get(f"{BASE}/profiles/{old['profile_id']}/state").json()
    fresh = new_profile(client, "J-new", save="no", profile_id=old["profile_id"]).json()
    # 旧档案上迟到的请求仍按自己的版本校验，只影响旧档案。
    late = client.post(f"{BASE}/profiles/{old['profile_id']}/confirm",
                       json={"op_id": "J-late", "expected_version": 99})
    assert late.status_code == 409
    late_ok = send(client, old["profile_id"], "补充：检查日期是 2025-09-19",
                   "J-late-msg")
    assert late_ok["profile_id"] == old["profile_id"]
    new_state = client.get(f"{BASE}/profiles/{fresh['profile_id']}/state").json()
    assert new_state["version"] == 0
    assert new_state["confirmed_data"] is None
    assert new_state["messages"] == []
    assert new_state["draft"] is None
    # 旧档案的待确认动作只留在旧档案，新档案没有待处理动作。
    assert client.get(f"{BASE}/profiles/{fresh['profile_id']}/state").json()[
        "pending_actions"] == []
    assert client.get(f"{BASE}/profiles/{old['profile_id']}/state").json()[
        "confirmed_data"]["visits"][0]["date"] == old_state["confirmed_data"][
            "visits"][0]["date"]


def test_repeated_new_profile_request_is_idempotent(client, model):
    """验收 18：重复新建请求幂等，不产生多个意外档案。"""
    old, _ = confirmed(client, model, [visit_2025()], prefix="K")
    first = new_profile(client, "K-new", save="no", profile_id=old["profile_id"])
    second = new_profile(client, "K-new", save="no", profile_id=old["profile_id"])
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["profile_id"] == first.json()["profile_id"]
    assert len(client.get(f"{BASE}/profiles").json()) == 2


def test_pending_action_cannot_leak_across_profiles(client, model):
    """验收 18：旧档案的待确认动作不能在新档案上被执行。"""
    old, _ = confirmed(client, model, [visit_2024(), visit_2025()], prefix="L")
    ask = send(client, old["profile_id"], "删除去年的记录", "L-delete")
    assert ask["pending_actions"]
    fresh = new_profile(client, "L-new", save="no", profile_id=old["profile_id"]).json()
    leaked = client.post(f"{BASE}/profiles/{fresh['profile_id']}/messages",
                         json={"op_id": "L-leak", "text": "确认删除"})
    assert leaked.status_code == 200
    assert leaked.json()["confirmed_data"] is None
    assert leaked.json()["pending_actions"] == []
    assert len(client.get(f"{BASE}/profiles/{old['profile_id']}/state").json()[
        "confirmed_data"]["visits"]) == 2


# ---------------------------------------------------------------- 验收 19


def test_two_tabs_keep_their_own_profile(client, model):
    """验收 19：两个标签页分别操作不同档案，互不串档。"""
    tab_a, _ = confirmed(client, model, [visit_2025()], prefix="M")
    tab_b = new_profile(client, "N-new", save="no", profile_id=tab_a["profile_id"]).json()
    text, result = make_report([visit_2024()], profile=PROFILE)
    model.extraction = result
    sent = send(client, tab_b["profile_id"], text, "N-upload")
    assert sent["profile_id"] == tab_b["profile_id"]
    a_state = client.get(f"{BASE}/profiles/{tab_a['profile_id']}/state").json()
    assert a_state["draft"] is None
    assert len(a_state["confirmed_data"]["visits"]) == 1
    b_state = client.get(f"{BASE}/profiles/{tab_b['profile_id']}/state").json()
    assert b_state["confirmed_data"] is None
    assert len(b_state["draft"]["visits"]) == 1
    listing = {item["profile_id"] for item in client.get(f"{BASE}/profiles").json()}
    assert {tab_a["profile_id"], tab_b["profile_id"]} <= listing


def test_new_profile_failure_keeps_workspace_untouched(client, model, monkeypatch):
    """验收 19：新建接口失败时不串档、不半清空。"""
    old, _ = confirmed(client, model, [visit_2025()], prefix="O")
    upload(client, model, old["profile_id"], "O-draft", [visit_2024()])
    before = client.get(f"{BASE}/profiles/{old['profile_id']}/state").json()

    def boom(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(PL, "generate_snapshot", boom)
    failed = new_profile(client, "O-new", save="yes", profile_id=old["profile_id"])
    assert failed.status_code == 400
    monkeypatch.undo()
    after = client.get(f"{BASE}/profiles/{old['profile_id']}/state").json()
    assert after["draft"] == before["draft"]
    assert after["confirmed_data"] == before["confirmed_data"]


def test_restart_keeps_current_profile_but_clears_draft(client, model):
    """验收 19：“重新开始整理”清空草稿与待执行动作，保留已确认资料与规划。"""
    profile, _ = confirmed(client, model, [visit_2025()], prefix="P")
    plan(client, profile["profile_id"], "P-plan", expected_version=1)
    upload(client, model, profile["profile_id"], "P-draft", [visit_2024()])
    ask = send(client, profile["profile_id"], "删除去年的记录", "P-delete")
    assert ask["pending_actions"]

    restarted = client.post(f"{BASE}/profiles/{profile['profile_id']}/restart",
                            json={"op_id": "P-restart"})
    assert restarted.status_code == 200, restarted.text
    body = restarted.json()
    assert body["profile_id"] == profile["profile_id"]
    assert body["draft"] is None
    assert body["pending_actions"] == []
    assert body["messages"] == []
    assert len(body["confirmed_data"]["visits"]) == 1
    assert body["version"] == 1
    assert body["current_snapshot"]["status"] == "current"
    # 重新开始后撤销上下文清空。
    undone = send(client, profile["profile_id"], "撤销", "P-undo")
    assert undone["rejected_actions"]


def test_new_profile_after_restart_does_not_restore_old_cache(client, model):
    """验收 19：刷新后继续新档案，不恢复旧人的缓存内容。"""
    old, _ = confirmed(client, model, [visit_2025()], prefix="Q")
    upload(client, model, old["profile_id"], "Q-draft", [visit_2024()])
    fresh = new_profile(client, "Q-new", save="no", profile_id=old["profile_id"]).json()
    state = client.get(f"{BASE}/profiles/{fresh['profile_id']}/state").json()
    assert state["profile_id"] == fresh["profile_id"]
    assert state["display_name"] == fresh["display_name"]
    assert state["draft"] is None
    assert state["confirmed_data"] is None
    assert state["messages"] == []
    assert state["unknowns"] == []
