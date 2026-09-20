import json
import threading

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.schemas.prevention import PreventionRequest
from app.schemas.smart_import import ConfirmRequest, ImportRequest
from app.services.smart_import import extract

router = APIRouter(prefix="/prevention/smart-import", tags=["智能资料导入"])
lock = threading.Lock()


@router.get("/status")
def status():
    settings = get_settings()
    try:
        with httpx.Client(timeout=3, trust_env=False) as client:
            response = client.get(settings.import_model_url.rstrip("/") + "/api/tags")
            response.raise_for_status()
            models = [m["name"] for m in response.json()["models"]]
        ready = settings.import_model in models
        return {"ready": ready, "model": settings.import_model,
                "message": "本地模型已就绪" if ready else "请先运行智能导入模型安装脚本"}
    except (httpx.HTTPError, ValueError, KeyError):
        return {"ready": False, "model": settings.import_model,
                "message": "本地模型服务未启动，请运行 start-smart-import.cmd"}


@router.post("/extract")
async def extraction(request: Request):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 11_500_000:
            raise HTTPException(413, "上传内容超过限制，单文件最多 8 MB")
    try:
        body = ImportRequest.model_validate_json(data)
    except (ValidationError, ValueError):
        raise HTTPException(422, "输入格式错误或超过大小限制") from None
    if not lock.acquire(blocking=False):
        raise HTTPException(429, "正在处理另一份资料，请稍后再试")
    try:
        return await run_in_threadpool(extract, body)
    except httpx.TimeoutException:
        raise HTTPException(504, "模型处理超时，请减少页数后重试") from None
    except httpx.HTTPError:
        raise HTTPException(503, "模型服务不可用，请检查本地模型是否已安装和启动") from None
    except ValidationError:
        raise HTTPException(422, "模型返回字段未通过校验，请检查原文或改用手动录入") from None
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(422, "资料或模型输出无法解析，请检查文件、页数及文字内容") from None
    except Exception:
        # Do not leak document content, file internals or model responses to logs/errors.
        raise HTTPException(422, "文件读取失败，支持未加密 PDF、DOCX 正文及清晰图片") from None
    finally:
        lock.release()


@router.post("/confirm")
def confirm(body: ConfirmRequest):
    try:
        intake = PreventionRequest.model_validate(body.intake)
    except ValidationError as exc:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        raise HTTPException(422, errors) from None
    intake.source_note = ("AI 提取后经用户核对；" + intake.source_note)[:500]
    return {"intake": intake.model_dump(mode="json")}
