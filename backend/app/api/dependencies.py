from collections.abc import Generator
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import Select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Patient
from app.models.enums import AccountRole
from app.services.auth_service import AuthError, AuthService


def get_db() -> Generator[Session, None, None]:
    """为一次请求提供数据库会话；业务查询应继续委托给 Repository。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@dataclass(frozen=True)
class Principal:
    """当前请求的调用主体；未启用鉴权时是匿名管理员，仅用于本地开发与演示。"""

    account_id: str | None
    username: str
    display_name: str
    role: AccountRole
    authenticated: bool

    @property
    def is_admin(self) -> bool:
        return self.role is AccountRole.ADMIN

    @property
    def can_write(self) -> bool:
        return self.role.can_write


ANONYMOUS_PRINCIPAL = Principal(
    account_id=None,
    username="anonymous",
    display_name="开发模式匿名调用",
    role=AccountRole.ADMIN,
    authenticated=False,
)


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def get_current_principal(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),  # noqa: B008
) -> Principal:
    """解析 Bearer 令牌；未启用鉴权且未带令牌时返回匿名管理员，保证旧流程可用。"""

    token = extract_bearer_token(authorization)
    if token:
        try:
            session = AuthService(db).resolve_session(token)
        except AuthError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.message,
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        account = session.account
        return Principal(
            account_id=account.id,
            username=account.username,
            display_name=account.display_name,
            role=account.role,
            authenticated=True,
        )
    if get_settings().auth_required:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要登录后访问",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return ANONYMOUS_PRINCIPAL


MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def require_write_access(
    request: Request,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
) -> Principal:
    """只读角色不能修改业务数据；读取请求不受影响。"""

    if request.method in MUTATING_METHODS and not principal.can_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前角色为只读，不能修改数据",
        )
    return principal


def require_admin(
    principal: Principal = Depends(get_current_principal),  # noqa: B008
) -> Principal:
    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该操作需要管理员角色",
        )
    return principal


def can_access_patient(principal: Principal, patient: Patient) -> bool:
    """访问规则：管理员与开发模式可见全部；其余账号只能看自己名下档案。"""

    if not principal.authenticated or principal.is_admin:
        return True
    return patient.owner_account_id is not None and patient.owner_account_id == principal.account_id


def scope_patient_statement(statement: Select, principal: Principal) -> Select:
    """把档案查询限制在调用主体可见范围内。"""

    if not principal.authenticated or principal.is_admin:
        return statement
    return statement.where(Patient.owner_account_id == principal.account_id)


def ensure_patient_access(db: Session, principal: Principal, patient_id: str) -> Patient:
    """取档案并校验权限；不存在返回 404，越权返回 403。"""

    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="档案不存在")
    if not can_access_patient(principal, patient):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该账号无权访问此档案",
        )
    return patient
