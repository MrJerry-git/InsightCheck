from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import Principal, require_write_access
from app.ml.interfaces import RecommendationModel
from app.ml.recommendation.schemas import (
    RecommendationRankingRequest,
    RecommendationRankingResponse,
)
from app.services.recommendation_ranking_service import RecommendationRankingService

router = APIRouter(prefix="/recommendation-ranking", tags=["recommendation-ranking"])


def get_recommendation_model(request: Request) -> RecommendationModel:
    model = getattr(request.app.state, "recommendation_model", None)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="推荐模型制品尚未加载",
        )
    return model


RecommendationModelDependency = Annotated[
    RecommendationModel, Depends(get_recommendation_model)
]
Caller = Annotated[Principal, Depends(require_write_access)]


@router.post("/rank", response_model=RecommendationRankingResponse)
def rank_exam_items(
    payload: RecommendationRankingRequest,
    principal: Caller,
    model: RecommendationModelDependency,
) -> RecommendationRankingResponse:
    return RecommendationRankingService(model).rank(payload)
