from collections.abc import Generator

from sqlalchemy.orm import Session

from app.core.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """为一次请求提供数据库会话；业务查询应继续委托给 Repository。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
