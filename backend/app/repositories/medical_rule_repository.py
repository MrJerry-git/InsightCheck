from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import MedicalRule
from app.rules.models import (
    MedicalRuleDefinition,
    RuleAction,
    RuleType,
)


class MedicalRuleRepository:
    """Reads the current database rule rows for each evaluation; no rule cache is used."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_applicable(self, exam_item_id: str) -> list[MedicalRuleDefinition]:
        statement = (
            select(MedicalRule)
            .where(
                or_(
                    MedicalRule.exam_item_id.is_(None),
                    MedicalRule.exam_item_id == exam_item_id,
                )
            )
            .order_by(
                MedicalRule.priority.desc(),
                MedicalRule.rule_code.asc(),
                MedicalRule.version.asc(),
            )
            .execution_options(populate_existing=True)
        )
        return [self._to_definition(entity) for entity in self.session.scalars(statement)]

    @staticmethod
    def _to_definition(entity: MedicalRule) -> MedicalRuleDefinition:
        return MedicalRuleDefinition(
            rule_code=entity.rule_code,
            rule_type=RuleType(entity.rule_type),
            exam_item_id=entity.exam_item_id,
            condition=entity.condition_json,
            action=RuleAction(entity.action.value),
            priority=entity.priority,
            source=entity.source,
            version=entity.version,
            enabled=entity.enabled,
        )
