"""对话式档案管理的请求/响应结构（技术字段不直接展示给用户）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.smart_import import ImportFile


class ConversationMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: str = Field(min_length=1, max_length=80)
    text: str = Field(default="", max_length=16000)
    file: ImportFile | None = None
    expected_version: int | None = Field(default=None, ge=0)
    # 会话绑定：旧会话（已被“新建档案”或“重新开始整理”替换）不得迟到写入。
    session_id: str | None = Field(default=None, max_length=36)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: str = Field(min_length=1, max_length=80)
    # 必填：用户确认时必须声明自己看到的是哪一版草稿（审核 P1）。
    expected_draft_version: int = Field(ge=0)
    expected_version: int | None = Field(default=None, ge=0)
    session_id: str | None = Field(default=None, max_length=36)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: str = Field(min_length=1, max_length=80)
    expected_version: int | None = Field(default=None, ge=0)
    session_id: str | None = Field(default=None, max_length=36)


class RestartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: str = Field(min_length=1, max_length=80)
    session_id: str | None = Field(default=None, max_length=36)


class SaveCurrentOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str | None = Field(default=None, max_length=36)
    save: Literal["yes", "no", "cancel"]


class NewProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: str = Field(min_length=1, max_length=80)
    display_name: str | None = Field(default=None, max_length=60)
    save_current: SaveCurrentOption | None = None
