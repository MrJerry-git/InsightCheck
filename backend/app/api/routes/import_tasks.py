"""T03：文件导入任务接口（上传、进度、校对、确认入库、重试、取消）。"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    Principal,
    ensure_patient_access,
    get_current_principal,
    get_db,
    require_write_access,
)
from app.models import ImportTask
from app.models.enums import ImportTaskStatus
from app.services.import_tasks import ImportTaskError, ImportTaskService

router = APIRouter(prefix="/imports/tasks", tags=["import-tasks"])


class RowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_id: str = Field(min_length=1, max_length=20)
    date: str | None = None
    metric_code: str | None = Field(default=None, max_length=64)
    original_name: str | None = Field(default=None, max_length=200)
    original_value: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=50)
    reference_min: float | None = None
    reference_max: float | None = None
    include: bool | None = None


class PreviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[RowUpdate] = Field(min_length=1, max_length=200)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_duplicate: bool = False
    merge_same_day: bool = False


def service(db: Session) -> ImportTaskService:
    return ImportTaskService(db)


def task_or_404(db: Session, principal: Principal, task_id: str) -> ImportTask:
    task = db.get(ImportTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="导入任务不存在")
    ensure_patient_access(db, principal, task.patient_id)
    return task


def translate(exc: ImportTaskError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"message": exc.message,
                                                             "details": exc.details})


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_task(
    file: UploadFile = File(...),  # noqa: B008
    patient_id: str = Form(...),
    request_id: str | None = Form(default=None),
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """上传文件创建解析任务；返回待校对预览，不直接写业务记录。"""

    patient = ensure_patient_access(db, principal, patient_id)
    raw = await file.read()
    try:
        task = service(db).create_task(
            patient=patient,
            filename=file.filename or "upload",
            content_type=file.content_type,
            raw=raw,
            request_id=request_id,
            actor_account_id=principal.account_id,
        )
    except ImportTaskError as exc:
        raise translate(exc) from exc
    return service(db).serialize(task)


@router.get("")
def list_tasks(
    patient_id: str | None = Query(default=None),
    task_status: ImportTaskStatus | None = Query(default=None, alias="status"),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    if patient_id is not None:
        ensure_patient_access(db, principal, patient_id)
    statement = select(ImportTask).order_by(ImportTask.created_at.desc()).limit(limit)
    if patient_id is not None:
        statement = statement.where(ImportTask.patient_id == patient_id)
    if task_status is not None:
        statement = statement.where(ImportTask.status == task_status)
    tasks = list(db.scalars(statement))
    if patient_id is None and not principal.is_admin:
        # 非管理员只能看到自己名下档案的任务，逐一校验归属。
        tasks = [task for task in tasks if _visible(db, principal, task)]
    return [service(db).serialize(task) for task in tasks]


def _visible(db: Session, principal: Principal, task: ImportTask) -> bool:
    if not principal.authenticated or principal.is_admin:
        return True
    from app.api.dependencies import can_access_patient
    from app.models import Patient

    patient = db.get(Patient, task.patient_id)
    return patient is not None and can_access_patient(principal, patient)


@router.get("/{task_id}")
def get_task(
    task_id: str,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    return service(db).serialize(task_or_404(db, principal, task_id))


@router.patch("/{task_id}")
def update_preview(
    task_id: str,
    payload: PreviewUpdate,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """逐字段校对：修正日期、指标、数值、单位与参考区间后重新校验。"""

    task = task_or_404(db, principal, task_id)
    try:
        updated = service(db).update_rows(
            task, [row.model_dump(exclude_unset=True) for row in payload.rows]
        )
    except ImportTaskError as exc:
        raise translate(exc) from exc
    return service(db).serialize(updated)


@router.post("/{task_id}/confirm")
def confirm_task(
    task_id: str,
    payload: ConfirmRequest,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """事务性入库：全部成功或全部回滚，重复文件与同日冲突需显式确认。"""

    task = task_or_404(db, principal, task_id)
    try:
        summary = service(db).confirm(
            task,
            allow_duplicate=payload.allow_duplicate,
            merge_same_day=payload.merge_same_day,
            actor_account_id=principal.account_id,
        )
    except ImportTaskError as exc:
        raise translate(exc) from exc
    return {"task_id": task.id, "status": task.status.value, "result": summary}


@router.post("/{task_id}/retry")
def retry_task(
    task_id: str,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """重试解析：失败或已取消的任务重新解析，不重复新增已入库记录。"""

    task = task_or_404(db, principal, task_id)
    if task.status is ImportTaskStatus.CONFIRMED:
        raise HTTPException(status_code=409, detail="已入库的任务不能重新解析，请新建任务")
    try:
        parsed = service(db).parse(task)
    except ImportTaskError as exc:
        raise translate(exc) from exc
    return service(db).serialize(parsed)


@router.delete("/{task_id}")
def cancel_task(
    task_id: str,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """取消任务并清理临时文件；已入库任务不能取消。"""

    task = task_or_404(db, principal, task_id)
    try:
        cancelled = service(db).cancel(task)
    except ImportTaskError as exc:
        raise translate(exc) from exc
    return service(db).serialize(cancelled)
