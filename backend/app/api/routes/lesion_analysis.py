from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_db, require_write_access
from app.features.lesion.schemas import (
    LesionDemoAnalysisResult,
    LesionMatchingRequest,
    LesionMatchingResult,
    LesionTrendRequest,
    LesionTrendResult,
)
from app.services.crud import EntityNotFoundError
from app.services.lesion_analysis_service import LesionAnalysisService

router = APIRouter(prefix="/lesion-analysis", tags=["lesion-analysis"])
Caller = Annotated[Principal, Depends(require_write_access)]


@router.post("/match", response_model=LesionMatchingResult)
def match_lesions(payload: LesionMatchingRequest, principal: Caller) -> LesionMatchingResult:
    return LesionAnalysisService().match(payload)


@router.post("/trend", response_model=LesionTrendResult)
def analyze_lesion_trend(payload: LesionTrendRequest, principal: Caller) -> LesionTrendResult:
    return LesionAnalysisService().analyze_trend(payload)


@router.get("/demo", response_model=LesionDemoAnalysisResult)
def get_demo_analysis(
    principal: Caller,
    db: Session = Depends(get_db),  # noqa: B008
) -> LesionDemoAnalysisResult:
    try:
        return LesionAnalysisService().get_demo_analysis(db)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
