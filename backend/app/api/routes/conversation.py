"""对话式体检档案管理接口（前缀 /api/v1/prevention/conversation）。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.schemas.conversation import (
    ConfirmRequest,
    ConversationMessageRequest,
    NewProfileRequest,
    PlanRequest,
    RestartRequest,
)
from app.services.conversation import model as M
from app.services.conversation import orchestrator as O
from app.services.conversation.errors import Busy, ConversationError

router = APIRouter(prefix="/prevention/conversation", tags=["对话式体检档案管理"])
DB = Annotated[Session, Depends(get_db)]

# 与 smart-import 一致：单 worker 串行处理模型请求，忙时明确返回 429。
lock = threading.Lock()
Handler = Callable[[], tuple[int, dict]]


def _run(handler: Handler) -> JSONResponse:
    if not lock.acquire(blocking=False):
        busy = Busy("正在处理上一份资料，请稍后再试；已保存内容不受影响。")
        return JSONResponse(status_code=busy.http_status, content=busy.payload())
    try:
        code, payload = handler()
    except ConversationError as exc:
        return JSONResponse(status_code=exc.http_status, content=exc.payload())
    finally:
        lock.release()
    return JSONResponse(status_code=code, content=payload)


def _read(handler: Callable[[], object]) -> JSONResponse:
    try:
        return JSONResponse(status_code=200, content=handler())
    except ConversationError as exc:
        return JSONResponse(status_code=exc.http_status, content=exc.payload())


@router.get("/status")
def status():
    return M.model_status()


@router.get("/profiles")
def profiles(db: DB):
    return _read(lambda: O.list_profiles(db))


@router.post("/profiles", status_code=201)
def create_profile(body: NewProfileRequest, db: DB):
    return _run(lambda: O.create_profile(db, body))


@router.get("/profiles/{profile_id}/state")
def state(profile_id: str, db: DB):
    return _read(lambda: O.restore_session(db, profile_id))


@router.post("/profiles/{profile_id}/messages")
def messages(profile_id: str, body: ConversationMessageRequest, db: DB):
    return _run(lambda: O.handle_message(db, profile_id, body))


@router.post("/profiles/{profile_id}/confirm")
def confirm(profile_id: str, body: ConfirmRequest, db: DB):
    return _run(lambda: O.confirm_profile(db, profile_id, body))


@router.post("/profiles/{profile_id}/restart")
def restart(profile_id: str, body: RestartRequest, db: DB):
    return _run(lambda: O.restart_profile(db, profile_id, body))


@router.post("/profiles/{profile_id}/plan")
def plan(profile_id: str, body: PlanRequest, db: DB):
    return _run(lambda: O.generate_plan(db, profile_id, body))


@router.get("/profiles/{profile_id}/plans")
def plans(profile_id: str, db: DB):
    return _read(lambda: O.list_snapshots(db, profile_id))


@router.get("/profiles/{profile_id}/plans/{snapshot_id}")
def snapshot(profile_id: str, snapshot_id: str, db: DB):
    return _read(lambda: O.get_snapshot(db, profile_id, snapshot_id))
