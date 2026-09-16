from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.rules.models import RuleEvaluationRequest, RuleEvaluationResult
from app.services.medical_rule_service import MedicalRuleEngineService

router = APIRouter(prefix="/rule-engine", tags=["rule-engine"])

DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("/evaluate", response_model=RuleEvaluationResult)
def evaluate_exam_item(
    payload: RuleEvaluationRequest,
    session: DatabaseSession,
) -> RuleEvaluationResult:
    return MedicalRuleEngineService(session).evaluate(payload)
