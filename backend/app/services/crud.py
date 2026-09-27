from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.ownership import scope_statement
from app.models.base import Base
from app.repositories import SqlAlchemyRepository

if TYPE_CHECKING:  # 仅类型标注需要，避免运行期循环导入
    from app.api.dependencies import Principal

ModelT = TypeVar("ModelT", bound=Base)


class EntityNotFoundError(Exception):
    pass


class EntityConflictError(Exception):
    pass


class CrudService(Generic[ModelT]):
    """为基础维护操作提供一致的事务和错误语义。"""

    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self.session = session
        self.repository = SqlAlchemyRepository(session, model)

    def create(self, payload: BaseModel) -> ModelT:
        return self.create_values(payload.model_dump())

    def create_values(self, values: dict[str, Any]) -> ModelT:
        try:
            entity = self.repository.add(values)
            self.session.commit()
            self.session.refresh(entity)
            return entity
        except IntegrityError as exc:
            self.session.rollback()
            raise EntityConflictError("记录违反唯一性、外键或检查约束") from exc

    def get(self, entity_id: str) -> ModelT:
        entity = self.repository.get(entity_id)
        if entity is None:
            raise EntityNotFoundError(entity_id)
        return entity

    def list(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        scope: tuple[type[ModelT], Principal] | None = None,
    ) -> list[ModelT]:
        transform = None
        if scope is not None:
            model, principal = scope
            transform = lambda statement: scope_statement(statement, model, principal)  # noqa: E731
        return self.repository.list(offset=offset, limit=limit, transform=transform)

    def update(self, entity_id: str, payload: BaseModel) -> ModelT:
        entity = self.get(entity_id)
        values: dict[str, Any] = payload.model_dump(exclude_unset=True)
        try:
            entity = self.repository.update(entity, values)
            self.session.commit()
            self.session.refresh(entity)
            return entity
        except IntegrityError as exc:
            self.session.rollback()
            raise EntityConflictError("记录违反唯一性、外键或检查约束") from exc

    def delete(self, entity_id: str) -> None:
        entity = self.get(entity_id)
        try:
            self.repository.delete(entity)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise EntityConflictError("记录仍被其他数据引用，不能删除") from exc
