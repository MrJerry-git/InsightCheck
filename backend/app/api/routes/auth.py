"""账号、登录与账号管理接口（T01）。"""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import (
    Principal,
    extract_bearer_token,
    get_current_principal,
    get_db,
    require_admin,
)
from app.schemas.auth import (
    AccountCreate,
    AccountRead,
    AccountUpdate,
    LoginRequest,
    LogoutResult,
    PasswordChange,
    PasswordReset,
    SessionRead,
)
from app.services.auth_service import AuthError, AuthService, InvalidCredentialsError

router = APIRouter(prefix="/auth", tags=["accounts"])


def _translate(exc: AuthError) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return HTTPException(status_code=exc.status_code, detail=exc.message, headers=headers)


@router.post("/login", response_model=SessionRead)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> SessionRead:  # noqa: B008
    """用户名 + 口令换取会话令牌；失败不区分“用户不存在”和“口令错误”。"""

    try:
        token, session, account = AuthService(db).login(payload.username, payload.password)
    except AuthError as exc:
        raise _translate(exc) from exc
    return SessionRead(
        token=token,
        expires_at=session.expires_at,
        account=AccountRead.model_validate(account),
    )


@router.get("/me", response_model=AccountRead)
def read_me(
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AccountRead:
    if not principal.authenticated or principal.account_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前请求没有登录账号")
    account = AuthService(db).get_account(principal.account_id)
    return AccountRead.model_validate(account)


@router.post("/logout", response_model=LogoutResult)
def logout(
    all_sessions: bool = Query(default=False),
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),  # noqa: B008
) -> LogoutResult:
    """退出登录：默认只失效当前令牌，`all_sessions=true` 时失效该账号全部会话。"""

    if not principal.authenticated or principal.account_id is None:
        return LogoutResult(revoked_sessions=0)
    service = AuthService(db)
    if all_sessions:
        revoked = service.revoke_all_sessions(principal.account_id)
    else:
        revoked = service.revoke_session(extract_bearer_token(authorization) or "")
    return LogoutResult(revoked_sessions=revoked)


@router.post("/password", response_model=AccountRead)
def change_own_password(
    payload: PasswordChange,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),  # noqa: B008
) -> AccountRead:
    """本人改密码：校验当前口令，成功后失效其它会话。"""

    if not principal.authenticated or principal.account_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前请求没有登录账号")
    service = AuthService(db)
    try:
        service.authenticate(principal.username, payload.current_password)
    except InvalidCredentialsError as exc:
        raise _translate(exc) from exc
    except AuthError as exc:
        raise _translate(exc) from exc
    account = service.update_account(principal.account_id, password=payload.new_password)
    service.revoke_other_sessions(principal.account_id, extract_bearer_token(authorization) or "")
    return AccountRead.model_validate(account)


@router.get("/accounts", response_model=list[AccountRead])
def list_accounts(
    _: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[AccountRead]:
    return [AccountRead.model_validate(item) for item in AuthService(db).list_accounts()]


@router.post("/accounts", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreate,
    _: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AccountRead:
    """管理员创建账号；新账号默认启用，口令按强度规则校验。"""

    try:
        account = AuthService(db).create_account(
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
            role=payload.role,
        )
    except AuthError as exc:
        raise _translate(exc) from exc
    return AccountRead.model_validate(account)


@router.patch("/accounts/{account_id}", response_model=AccountRead)
def update_account(
    account_id: str,
    payload: AccountUpdate,
    principal: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AccountRead:
    """管理员改角色、停用或重置口令；不允许把自己降级或停用，避免锁死系统。"""

    if principal.account_id == account_id:
        if payload.role is not None and payload.role is not principal.role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能修改自己的角色，请由其他管理员操作",
            )
        if payload.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能停用当前登录账号",
            )
    try:
        account = AuthService(db).update_account(
            account_id,
            display_name=payload.display_name,
            role=payload.role,
            is_active=payload.is_active,
            password=payload.password,
        )
    except AuthError as exc:
        raise _translate(exc) from exc
    return AccountRead.model_validate(account)


@router.post("/accounts/{account_id}/password", response_model=AccountRead)
def reset_password(
    account_id: str,
    payload: PasswordReset,
    _: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AccountRead:
    """管理员重置口令；重置后该账号既有会话全部失效。"""

    service = AuthService(db)
    try:
        account = service.update_account(account_id, password=payload.password)
        service.revoke_all_sessions(account_id)
    except AuthError as exc:
        raise _translate(exc) from exc
    return AccountRead.model_validate(account)
