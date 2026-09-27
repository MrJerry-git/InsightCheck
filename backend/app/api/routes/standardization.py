from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_db, require_write_access
from app.features.lesion_terminology import LesionTerminology
from app.features.metric_normalizer import MetricNormalizer
from app.models import MetricDictionary
from app.schemas.domain import (
    LesionTerminologyRequest,
    LesionTerminologyResult,
    MetricNormalizationRequest,
    MetricNormalizationResult,
)

router = APIRouter(tags=["standardization"])
Caller = Annotated[Principal, Depends(require_write_access)]


@router.post("/metric-normalization/normalize", response_model=MetricNormalizationResult)
def normalize_metric(
    payload: MetricNormalizationRequest,
    principal: Caller,
    db: Session = Depends(get_db),  # noqa: B008
) -> MetricNormalizationResult:
    dictionaries = db.scalars(select(MetricDictionary)).all()
    return MetricNormalizer(dictionaries).normalize(payload)


@router.post("/lesion-terminology/normalize", response_model=LesionTerminologyResult)
def normalize_lesion_location(
    payload: LesionTerminologyRequest, principal: Caller
) -> LesionTerminologyResult:
    return LesionTerminology().normalize_location(payload.location)
