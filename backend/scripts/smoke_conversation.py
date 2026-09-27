"""Real local model end-to-end smoke check for the conversational archive.

Synthetic fixtures only; this is an engineering smoke check, not an accuracy
benchmark. Needs a running local Ollama with the configured import model.

Run from backend:
    .venv/Scripts/python.exe scripts/smoke_conversation.py
The full record (model name, inputs, elapsed seconds, replies, database changes)
is written to .runtime/conversation-smoke.json for the acceptance record.
"""

import json
import os
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
runtime = root / ".runtime"
runtime.mkdir(exist_ok=True)
database = runtime / "conversation-smoke.db"
if database.exists():
    database.unlink()
# 独立数据库：不触碰开发/比赛用的档案文件。
os.environ["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

BASE = "/api/v1/prevention/conversation"
ANSWER_RULES = [
    ("吸烟", "不吸烟"),
    ("单位", "mmol/L"),
    ("单位是 mg/dL", "mmol/L"),
    ("心血管", "没有心血管疾病"),
    ("妊娠", "未妊娠"),
    ("不适", "无不适"),
    ("日期", "2026-03-05"),
    ("性别", "女"),
]


def answer_for(question: str) -> str:
    for needle, reply in ANSWER_RULES:
        if needle in question:
            return reply
    return "不知道"


def main() -> int:
    settings = get_settings()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    record: list[dict] = []
    steps = 0

    def step(name: str, response, extra: dict | None = None) -> dict:
        nonlocal steps
        steps += 1
        body = response.json() if response.content else {}
        entry = {"step": steps, "name": name, "http": response.status_code,
                 "seconds": round(time.monotonic() - started, 2)}
        if isinstance(body, dict):
            entry["reply"] = body.get("reply")
            entry["questions"] = body.get("questions")
            entry["pending"] = [item.get("question")
                                for item in body.get("pending_actions") or []]
            entry["changed_summary"] = body.get("changed_summary")
            entry["rejected"] = body.get("rejected_actions")
            entry["version"] = body.get("version")
            entry["draft_version"] = body.get("draft_version")
        entry.update(extra or {})
        record.append(entry)
        print(f"[{steps}] {name}: HTTP {response.status_code} "
              f"({entry['seconds']}s) {entry.get('reply') or ''}")
        for question in entry.get("questions") or []:
            print(f"      ？ {question}")
        if entry.get("rejected"):
            print(f"      ! {entry['rejected']}")
        return body

    with TestClient(app) as client:
        started = time.monotonic()
        step("status", client.get(f"{BASE}/status"))
        profile = step("create profile", client.post(f"{BASE}/profiles",
                                                     json={"op_id": "smoke-1"}))
        profile_id = profile["profile_id"]
        step("database tables", client.get(f"{BASE}/profiles/{profile_id}/state"),
             {"tables": sorted(Base.metadata.tables)})

        for name in ("2025", "2026"):
            text = (root / f"docs/examples/conversational-import-demo-{name}.txt").read_text(
                encoding="utf-8")
            body = step(f"upload {name} report",
                        client.post(f"{BASE}/profiles/{profile_id}/messages",
                                    json={"op_id": f"smoke-upload-{name}", "text": text}))
            rounds = 0
            while (body.get("questions") or body.get("pending_actions")) and rounds < 6:
                question = (body.get("pending_actions") or [{}])[0].get("question") or \
                    (body["questions"] or [""])[0]
                rounds += 1
                body = step(f"answer {name} #{rounds}",
                            client.post(f"{BASE}/profiles/{profile_id}/messages",
                                        json={"op_id": f"smoke-answer-{name}-{rounds}",
                                              "text": answer_for(question)}))
            step(f"confirm {name}",
                 client.post(f"{BASE}/profiles/{profile_id}/confirm",
                             json={"op_id": f"smoke-confirm-{name}",
                                   "expected_version": body.get("version")}))

        plan = step("plan", client.post(f"{BASE}/profiles/{profile_id}/plan",
                                        json={"op_id": "smoke-plan",
                                              "expected_version": 2}))
        step("modify sbp", client.post(f"{BASE}/profiles/{profile_id}/messages",
                                       json={"op_id": "smoke-modify",
                                             "text": "2026-03-05 的收缩压改成 134 mmHg"}))
        step("re-plan", client.post(f"{BASE}/profiles/{profile_id}/plan",
                                    json={"op_id": "smoke-plan-2", "expected_version": 3}))
        state = step("state", client.get(f"{BASE}/profiles/{profile_id}/state"))

        with session_factory() as session:
            counts = {table: session.execute(
                __import__("sqlalchemy").text(f"SELECT COUNT(*) FROM {table}")).scalar()
                for table in ("profiles", "profile_drafts", "conversation_sessions",
                              "conversation_messages", "pending_actions", "action_logs",
                              "archive_snapshots")}
        record.append({"step": "database counts", "tables": counts})
        record.append({"step": "confirmed visits",
                       "visits": (state.get("confirmed_data") or {}).get("visits")})
        record.append({"step": "plan overall",
                       "codes": [item["code"] for item in (plan.get("overall") or [])],
                       "snapshot_version": plan.get("snapshot_version")})

    output = runtime / "conversation-smoke.json"
    output.write_text(json.dumps({"model": settings.import_model,
                                  "total_seconds": round(time.monotonic() - started, 2),
                                  "record": record}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(json.dumps({"database": counts,
                      "visits": len((state.get("confirmed_data") or {}).get("visits") or []),
                      "written": str(output)}, ensure_ascii=False))
    print("这是本地模型工程冒烟记录，不是识别准确率或临床验证。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
