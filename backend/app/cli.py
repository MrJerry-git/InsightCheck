"""账号初始化与运维命令（T01/T11）。

口令通过交互输入或环境变量提供，命令行参数不回显口令：

    python -m app.cli create-admin --username admin --display-name 管理员
    python -m app.cli reset-password --username admin
    python -m app.cli list-accounts

执行前先跑 ``python -m alembic upgrade head`` 建表。
"""

import argparse
import getpass
import os
import sys
from collections.abc import Sequence

from app.core.database import SessionLocal
from app.models.enums import AccountRole
from app.services.auth_service import AuthError, AuthService

PASSWORD_ENV_VAR = "XUNYING_ACCOUNT_PASSWORD"


def _read_password(confirm: bool = False) -> str:
    from_env = os.environ.get(PASSWORD_ENV_VAR)
    if from_env:
        return from_env
    password = getpass.getpass("口令: ")
    if confirm and getpass.getpass("再次输入口令: ") != password:
        raise SystemExit("两次输入的口令不一致")
    return password


def _create_admin(args: argparse.Namespace) -> int:
    with SessionLocal() as session:
        service = AuthService(session)
        account = service.create_account(
            username=args.username,
            password=_read_password(confirm=True),
            display_name=args.display_name or args.username,
            role=AccountRole.ADMIN,
        )
        print(f"已创建管理员账号 {account.username}（{account.id}）")
    return 0


def _reset_password(args: argparse.Namespace) -> int:
    with SessionLocal() as session:
        service = AuthService(session)
        account = service.get_account_by_username(args.username)
        service.update_account(account.id, password=_read_password(confirm=True))
        revoked = service.revoke_all_sessions(account.id)
        print(f"已重置 {account.username} 的口令，失效 {revoked} 个会话")
    return 0


def _list_accounts(_: argparse.Namespace) -> int:
    with SessionLocal() as session:
        for account in AuthService(session).list_accounts():
            state = "启用" if account.is_active else "停用"
            print(f"{account.username}\t{account.role.value}\t{state}\t{account.display_name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="循影定检账号运维命令")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-admin", help="创建管理员账号")
    create.add_argument("--username", required=True)
    create.add_argument("--display-name", default=None)
    create.set_defaults(handler=_create_admin)

    reset = subparsers.add_parser("reset-password", help="重置账号口令并失效其会话")
    reset.add_argument("--username", required=True)
    reset.set_defaults(handler=_reset_password)

    listing = subparsers.add_parser("list-accounts", help="列出账号")
    listing.set_defaults(handler=_list_accounts)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except AuthError as exc:
        print(f"操作失败：{exc.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - 手工执行的入口
    raise SystemExit(main())
