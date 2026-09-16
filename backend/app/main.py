from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "循影定检数据、特征与 DeepFM 体检项目匹配 API；"
            "匹配分数必须继续经过 Rule Engine。"
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    if settings.recommendation_artifact_path:
        from app.ml.recommendation.model import DeepFMRecommendationModel

        application.state.recommendation_model = DeepFMRecommendationModel.load(
            Path(settings.recommendation_artifact_path)
        )
    return application


app = create_app()
