"""数据库访问层。

第一阶段没有业务表，因此不创建没有真实调用方的 Repository 接口或实现。
"""

from app.repositories.base import SqlAlchemyRepository
from app.repositories.medical_rule_repository import MedicalRuleRepository

__all__ = ["MedicalRuleRepository", "SqlAlchemyRepository"]
