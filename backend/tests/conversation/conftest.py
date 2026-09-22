"""测试替身与人工资料构造工具：模型输出全部可模拟，不依赖真实模型。"""

from __future__ import annotations

from collections.abc import Iterator
from json import dumps as json_dumps

import httpx
import pytest
from fastapi.testclient import TestClient

BASE = "/api/v1/prevention/conversation"
MODEL = "qwen3-vl:4b-instruct"


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("fake", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> dict:
        return self.payload


class FakeOllama:
    """本地模型替身：按 format 区分“资料提取”与“对话动作提案”。"""

    def __init__(self, *, extraction: dict | None = None, proposal: dict | None = None,
                 error: Exception | None = None, ready: bool = True) -> None:
        self.extraction = extraction or {"sex": None, "visits": [{}], "evidence": [],
                                         "warnings": []}
        self.proposal = proposal or {"reply": "", "questions": [], "actions": []}
        self.error = error
        self.ready = ready
        self.calls: list[dict] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(httpx, "Client", lambda **_: self)

    def __enter__(self) -> FakeOllama:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def get(self, url: str) -> FakeResponse:
        if self.error:
            raise self.error
        names = [MODEL] if self.ready else []
        return FakeResponse({"models": [{"name": name} for name in names]})

    def post(self, url: str, json: dict | None = None) -> FakeResponse:  # noqa: A002
        body = json or {}
        self.calls.append(body)
        if self.error:
            raise self.error
        shape = json_dumps(body.get("format") or {}, ensure_ascii=False)
        if "evidence" in shape:
            content = self.extraction
        else:
            content = self.proposal
        return FakeResponse({"message": {"content": json_dumps(content, ensure_ascii=False,
                                                              default=str)}})


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> FakeOllama:
    fake = FakeOllama()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def client(test_app) -> Iterator[TestClient]:
    with TestClient(test_app) as test_client:
        yield test_client


_PROFILE_QUOTES = {
    ("sex", "male"): "性别：男",
    ("sex", "female"): "性别：女",
    ("known_cvd", False): "无冠心病",
    ("known_cvd", True): "已确诊冠心病",
    ("pregnant", False): "未妊娠",
    ("pregnant", True): "当前妊娠",
    ("symptomatic", False): "无不适",
    ("symptomatic", True): "目前胸痛",
}


def _visit_quote(name: str, value: object, unit: str) -> str:
    texts = {
        "date": f"检查日期：{value}",
        "age": f"年龄：{value} 岁",
        "sbp": f"收缩压 {value} mmHg",
        "total_c": f"总胆固醇 {value} {unit}",
        "hdl_c": f"HDL 胆固醇 {value} {unit}",
        "bmi": f"BMI {value}",
        "egfr": f"eGFR {value}",
        "dm": "已确诊糖尿病" if value else "无糖尿病",
        "smoking": "吸烟" if value else "不吸烟",
        "bp_tx": "使用降压药" if value else "未使用降压药",
        "statin": "使用他汀" if value else "未使用他汀",
        "hba1c": f"HbA1c {value}%",
        "fasting_glucose": f"空腹血糖 {value} {unit or 'mmol/L'}",
        "glucose_status": {"normal": "血糖结论：正常", "prediabetes": "血糖结论：糖尿病前期",
                           "diabetes": "血糖结论：糖尿病",
                           "unknown": "血糖结论未确认"}.get(str(value), ""),
    }
    return texts.get(name, "")


def make_report(visits: list[dict], *, profile: dict | None = None,
                title: str = "人工构造体检资料（测试用，不是真实患者）") -> tuple[str, dict]:
    """由字段值生成与原文逐字一致的 evidence，避免被服务端依据校验清空。"""
    profile = profile or {"sex": "male", "known_cvd": False, "pregnant": False,
                          "symptomatic": False}
    text_parts = [title]
    evidence: list[dict] = []
    extraction: dict = {"sex": None, "known_cvd": None, "pregnant": None,
                        "symptomatic": None, "visits": [], "warnings": []}
    for name, value in profile.items():
        if value is None:
            continue
        quote = _PROFILE_QUOTES.get((name, value))
        if quote is None:
            continue
        extraction[name] = value
        evidence.append({"path": name, "quote": quote})
        text_parts.append(quote)
    for index, raw in enumerate(visits):
        visit = dict(raw)
        unit = visit.get("chol_unit") or "mmol/L"
        row: dict = {}
        for name in ("date", "age", "sbp", "total_c", "hdl_c", "bmi", "egfr", "dm",
                     "smoking", "bp_tx", "statin", "hba1c", "fasting_glucose",
                     "glucose_status"):
            value = visit.get(name)
            if value is None or (name == "glucose_status" and value == "unknown"):
                continue
            quote = _visit_quote(name, value, unit)
            if not quote:
                continue
            row[name] = value
            evidence.append({"path": f"visits.{index}.{name}", "quote": quote})
            text_parts.append(quote)
        if visit.get("chol_unit"):
            row["chol_unit"] = visit["chol_unit"]
            quote = f"胆固醇单位 {unit}"
            evidence.append({"path": f"visits.{index}.chol_unit", "quote": unit})
            text_parts.append(quote)
        extraction["visits"].append(row)
    extraction["evidence"] = evidence
    return "\n".join(text_parts), extraction


def extract_result(visits: list[dict], **kwargs) -> dict:
    return make_report(visits, **kwargs)[1]


def proposal(reply: str = "", actions: list[dict] | None = None,
             questions: list[str] | None = None) -> dict:
    return {"reply": reply, "actions": actions or [], "questions": questions or []}


def create_profile(client: TestClient, op_id: str = "op-create") -> dict:
    response = client.post(f"{BASE}/profiles", json={"op_id": op_id})
    assert response.status_code == 201, response.text
    return response.json()


def send(client: TestClient, profile_id: str, text: str, op_id: str,
         **kwargs) -> dict:
    body = {"op_id": op_id, "text": text, **kwargs}
    response = client.post(f"{BASE}/profiles/{profile_id}/messages", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client: TestClient, profile_id: str, op_id: str, expected_version: int = 0,
            expected_draft_version: int | None = None, session_id: str | None = None):
    """确认必须携带当前草稿版本（审核 P1）；未显式指定时按当前状态取。"""

    if expected_draft_version is None:
        state = client.get(f"{BASE}/profiles/{profile_id}/state").json()
        expected_draft_version = state.get("draft_version", 0)
    body = {"op_id": op_id, "expected_version": expected_version,
            "expected_draft_version": expected_draft_version}
    if session_id is not None:
        body["session_id"] = session_id
    return client.post(f"{BASE}/profiles/{profile_id}/confirm",
                       json=body)


def stored_confirmed(client: TestClient, profile_id: str) -> dict | None:
    state = client.get(f"{BASE}/profiles/{profile_id}/state").json()
    return state["confirmed_data"]
