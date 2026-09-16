from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
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


@router.post("/match", response_model=LesionMatchingResult)
def match_lesions(payload: LesionMatchingRequest) -> LesionMatchingResult:
    return LesionAnalysisService().match(payload)


@router.post("/trend", response_model=LesionTrendResult)
def analyze_lesion_trend(payload: LesionTrendRequest) -> LesionTrendResult:
    return LesionAnalysisService().analyze_trend(payload)


@router.get("/demo", response_model=LesionDemoAnalysisResult)
def get_demo_analysis(db: Session = Depends(get_db)) -> LesionDemoAnalysisResult:  # noqa: B008
    try:
        return LesionAnalysisService().get_demo_analysis(db)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
