"""账号与会话的请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccountRole

USERNAME_PATTERN = r"^[A-Za-z0-9._-]{3,64}$"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str
    role: AccountRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class SessionRead(BaseModel):
    """登录成功响应；token 只在这一次返回，服务端只保存摘要。"""

    model_config = ConfigDict(extra="forbid")

    token: str
    expires_at: datetime
    token_type: str = "Bearer"
    account: AccountRead


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64, pattern=USERNAME_PATTERN)
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)
    role: AccountRole = AccountRole.DOCTOR


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: AccountRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=200)


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=10, max_length=200)


class PasswordChange(BaseModel):
    """本人修改口令：必须提供当前口令，避免会话被盗后直接换密。"""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


class LogoutResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revoked_sessions: int
