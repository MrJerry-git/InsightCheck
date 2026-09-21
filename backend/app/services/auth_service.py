"""账号、会话与口令的业务逻辑。

事务边界在本服务内管理；路由只负责把领域错误映射成 HTTP 状态码。
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    DEFAULT_ITERATIONS,
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.models import Account, AuthSession
from app.models.enums import AccountRole

SESSION_TOUCH_INTERVAL = timedelta(minutes=5)


class AuthError(Exception):
    """认证/账号领域错误，由路由映射为具体状态码。"""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidCredentialsError(AuthError):
    status_code = 401


class InactiveAccountError(AuthError):
    status_code = 403


class SessionExpiredError(AuthError):
    status_code = 401


class AccountNotFoundError(AuthError):
    status_code = 404


class DuplicateUsernameError(AuthError):
    status_code = 409


class PasswordPolicyError(AuthError):
    status_code = 422


def _derive_password(password: str, iterations: int) -> tuple[str, str, int]:
    try:
        return hash_password(password, iterations=iterations)
    except ValueError as exc:
        raise PasswordPolicyError(str(exc)) from exc


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime) -> datetime:
    """SQLite 读回的是无时区时间，统一补成 UTC 后再比较。"""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AuthService:
    def __init__(
        self,
        db: Session,
        *,
        now: Callable[[], datetime] = utcnow,
        session_ttl: timedelta | None = None,
        iterations: int | None = None,
    ) -> None:
        self.db = db
        self._now = now
        settings = get_settings()
        self._session_ttl = session_ttl or timedelta(minutes=settings.session_ttl_minutes)
        self._iterations = iterations or settings.password_hash_iterations or DEFAULT_ITERATIONS

    # ---- 账号 -------------------------------------------------------------
    def create_account(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None = None,
        role: AccountRole = AccountRole.DOCTOR,
    ) -> Account:
        normalized = username.strip()
        existing = self.db.scalar(select(Account).where(Account.username == normalized))
        if existing is not None:
            raise DuplicateUsernameError("用户名已存在")
        password_hash, salt, iterations = _derive_password(password, self._iterations)
        account = Account(
            username=normalized,
            display_name=(display_name or normalized).strip(),
            role=role,
            password_hash=password_hash,
            password_salt=salt,
            password_iterations=iterations,
            is_active=True,
        )
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        return account

    def list_accounts(self) -> list[Account]:
        return list(self.db.scalars(select(Account).order_by(Account.username)))

    def get_account_by_username(self, username: str) -> Account:
        account = self.db.scalar(select(Account).where(Account.username == username.strip()))
        if account is None:
            raise AccountNotFoundError("账号不存在")
        return account

    def get_account(self, account_id: str) -> Account:
        account = self.db.get(Account, account_id)
        if account is None:
            raise AccountNotFoundError("账号不存在")
        return account

    def update_account(
        self,
        account_id: str,
        *,
        display_name: str | None = None,
        role: AccountRole | None = None,
        is_active: bool | None = None,
        password: str | None = None,
    ) -> Account:
        account = self.get_account(account_id)
        if display_name is not None:
            account.display_name = display_name.strip()
        if role is not None:
            account.role = role
        if password is not None:
            account.password_hash, account.password_salt, account.password_iterations = (
                _derive_password(password, self._iterations)
            )
        if is_active is not None and is_active != account.is_active:
            account.is_active = is_active
            if not is_active:
                # 停用账号必须立即失效已有会话。
                self._revoke_all(account.id)
        self.db.commit()
        self.db.refresh(account)
        return account

    # ---- 登录与会话 -------------------------------------------------------
    def authenticate(self, username: str, password: str) -> Account:
        account = self.db.scalar(select(Account).where(Account.username == username.strip()))
        if account is None or not verify_password(
            password,
            password_hash=account.password_hash,
            salt=account.password_salt,
            iterations=account.password_iterations,
        ):
            raise InvalidCredentialsError("用户名或口令不正确")
        if not account.is_active:
            raise InactiveAccountError("账号已停用，请联系管理员")
        return account

    def login(self, username: str, password: str) -> tuple[str, AuthSession, Account]:
        account = self.authenticate(username, password)
        token, session = self.issue_session(account)
        account.last_login_at = self._now()
        self.db.commit()
        self.db.refresh(account)
        return token, session, account

    def issue_session(
        self, account: Account, *, ttl: timedelta | None = None
    ) -> tuple[str, AuthSession]:
        token = generate_session_token()
        issued_at = self._now()
        session = AuthSession(
            account_id=account.id,
            token_hash=hash_session_token(token),
            expires_at=issued_at + (ttl or self._session_ttl),
            last_seen_at=issued_at,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return token, session

    def resolve_session(self, token: str) -> AuthSession:
        if not token:
            raise SessionExpiredError("缺少会话令牌")
        session = self.db.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_session_token(token))
        )
        now = self._now()
        if session is None or session.revoked_at is not None:
            raise SessionExpiredError("会话无效或已退出，请重新登录")
        if ensure_aware(session.expires_at) <= now:
            raise SessionExpiredError("会话已过期，请重新登录")
        account = session.account
        if account is None or not account.is_active:
            raise InactiveAccountError("账号已停用，请联系管理员")
        last_seen = session.last_seen_at
        if last_seen is None or now - ensure_aware(last_seen) >= SESSION_TOUCH_INTERVAL:
            session.last_seen_at = now
            self.db.commit()
        return session

    def revoke_session(self, token: str) -> int:
        session = self.db.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_session_token(token))
        )
        if session is None or session.revoked_at is not None:
            return 0
        session.revoked_at = self._now()
        self.db.commit()
        return 1

    def revoke_all_sessions(self, account_id: str) -> int:
        count = self._revoke_all(account_id)
        self.db.commit()
        return count

    def revoke_other_sessions(self, account_id: str, keep_token: str) -> int:
        """改密后失效该账号除当前令牌外的全部会话。"""

        keep_hash = hash_session_token(keep_token)
        sessions = self.db.scalars(
            select(AuthSession).where(
                AuthSession.account_id == account_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.token_hash != keep_hash,
            )
        ).all()
        now = self._now()
        for session in sessions:
            session.revoked_at = now
        self.db.commit()
        return len(sessions)

    def _revoke_all(self, account_id: str) -> int:
        sessions = self.db.scalars(
            select(AuthSession).where(
                AuthSession.account_id == account_id, AuthSession.revoked_at.is_(None)
            )
        ).all()
        now = self._now()
        for session in sessions:
            session.revoked_at = now
        return len(sessions)

    def count_active_sessions(self, account_id: str) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(AuthSession)
                .where(
                    AuthSession.account_id == account_id,
                    AuthSession.revoked_at.is_(None),
                )
            )
            or 0
        )
