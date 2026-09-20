from fastapi import APIRouter

from app.api.routes.crud import router as crud_router
from app.api.routes.health import router as health_router
from app.api.routes.imports import router as imports_router
from app.api.routes.lesion_analysis import router as lesion_analysis_router
from app.api.routes.prevention import router as prevention_router
from app.api.routes.recommendation_ranking import router as recommendation_ranking_router
from app.api.routes.rule_engine import router as rule_engine_router
from app.api.routes.standardization import router as standardization_router
from app.api.routes.workflow import router as workflow_router

api_router = APIRouter()
api_router.include_router(prevention_router)
api_router.include_router(health_router)
api_router.include_router(workflow_router)
api_router.include_router(imports_router)
api_router.include_router(standardization_router)
api_router.include_router(lesion_analysis_router)
api_router.include_router(recommendation_ranking_router)
api_router.include_router(rule_engine_router)
api_router.include_router(crud_router)
