from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class SqlAlchemyRepository(Generic[ModelT]):
    """只封装持久化操作；事务边界由 Service 管理。"""

    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    def add(self, values: dict[str, Any]) -> ModelT:
        entity = self.model(**values)
        self.session.add(entity)
        self.session.flush()
        return entity

    def get(self, entity_id: str) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def list(self, *, offset: int = 0, limit: int = 100) -> list[ModelT]:
        statement = select(self.model).offset(offset).limit(limit)
        created_at = getattr(self.model, "created_at", None)
        if created_at is not None:
            statement = statement.order_by(created_at.desc())
        return list(self.session.scalars(statement))

    def find_one_by(self, **criteria: Any) -> ModelT | None:
        statement = select(self.model).filter_by(**criteria).limit(1)
        return self.session.scalar(statement)

    def update(self, entity: ModelT, values: dict[str, Any]) -> ModelT:
        for field, value in values.items():
            setattr(entity, field, value)
        self.session.flush()
        return entity

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)
        self.session.flush()
