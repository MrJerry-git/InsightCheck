import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        # 生产环境关闭交互式文档，避免暴露完整接口面（可用 T08 管理接口替代运维查询）。
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None if settings.app_env == "production" else "/redoc",
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
        description=(
            "循影定检数据、特征与 DeepFM 体检项目匹配 API；"
            "匹配分数必须继续经过 Rule Engine。"
        ),
    )
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("xunying.request")

    @application.middleware("http")
    async def log_requests(request: Request, call_next):
        """为每个请求生成/透传 request id，并输出一行结构化访问日志。"""

        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.info(
                json.dumps(
                    {
                        "event": "request",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": 500,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                    ensure_ascii=False,
                )
            )
            raise
        response.headers["X-Request-ID"] = request_id
        logger.info(
            json.dumps(
                {
                    "event": "request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
                ensure_ascii=False,
            )
        )
        return response

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
