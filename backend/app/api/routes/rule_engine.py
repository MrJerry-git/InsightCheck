from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_db, require_write_access
from app.rules.models import RuleEvaluationRequest, RuleEvaluationResult
from app.services.medical_rule_service import MedicalRuleEngineService

router = APIRouter(prefix="/rule-engine", tags=["rule-engine"])

DatabaseSession = Annotated[Session, Depends(get_db)]
Caller = Annotated[Principal, Depends(require_write_access)]


@router.post("/evaluate", response_model=RuleEvaluationResult)
def evaluate_exam_item(
    payload: RuleEvaluationRequest,
    session: DatabaseSession,
    principal: Caller,
) -> RuleEvaluationResult:
    return MedicalRuleEngineService(session).evaluate(payload)
