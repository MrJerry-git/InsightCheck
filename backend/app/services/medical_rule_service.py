from sqlalchemy.orm import Session

from app.repositories.medical_rule_repository import MedicalRuleRepository
from app.rules.engine import RuleEngine
from app.rules.models import RuleEvaluationRequest, RuleEvaluationResult


class MedicalRuleEngineService:
    """Loads current persistence state and delegates all decisions to RuleEngine."""

    def __init__(
        self,
        session: Session,
        *,
        engine: RuleEngine | None = None,
        repository: MedicalRuleRepository | None = None,
    ) -> None:
        self.engine = engine or RuleEngine()
        self.repository = repository or MedicalRuleRepository(session)

    def evaluate(self, request: RuleEvaluationRequest) -> RuleEvaluationResult:
        rules = self.repository.list_applicable(request.exam_item.exam_item_id)
        return self.engine.evaluate(request, rules)
