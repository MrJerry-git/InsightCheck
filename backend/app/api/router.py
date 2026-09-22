from fastapi import APIRouter

from app.api.routes.admin import router as admin_router
from app.api.routes.analyses import router as analyses_router
from app.api.routes.auth import router as auth_router
from app.api.routes.conversation import router as conversation_router
from app.api.routes.crud import router as crud_router
from app.api.routes.health import router as health_router
from app.api.routes.import_tasks import router as import_tasks_router
from app.api.routes.imports import router as imports_router
from app.api.routes.lesion_analysis import router as lesion_analysis_router
from app.api.routes.plans import router as plans_router
from app.api.routes.prevention import router as prevention_router
from app.api.routes.recommendation_ranking import router as recommendation_ranking_router
from app.api.routes.records import router as records_router
from app.api.routes.reports import router as reports_router
from app.api.routes.rule_engine import router as rule_engine_router
from app.api.routes.smart_import import router as smart_import_router
from app.api.routes.standardization import router as standardization_router
from app.api.routes.workflow import router as workflow_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(analyses_router)
api_router.include_router(admin_router)
api_router.include_router(plans_router)
api_router.include_router(conversation_router)
api_router.include_router(smart_import_router)
api_router.include_router(prevention_router)
api_router.include_router(health_router)
api_router.include_router(workflow_router)
api_router.include_router(imports_router)
api_router.include_router(import_tasks_router)
api_router.include_router(standardization_router)
api_router.include_router(lesion_analysis_router)
api_router.include_router(recommendation_ranking_router)
api_router.include_router(rule_engine_router)
api_router.include_router(crud_router)
api_router.include_router(records_router)
api_router.include_router(reports_router)
