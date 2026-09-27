"""T02：记录修订历史查询接口。

修订是只读审计数据：既有记录可以按档案或按单条记录回看变更，用来解释
“这条数据是谁、什么时候、依据什么改的”。不提供改写历史的接口。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, ensure_patient_access, get_current_principal, get_db
from app.models import RecordRevision
from app.services.record_revisions import REVISION_ENTITY_TYPES, RecordRevisionService

router = APIRouter(tags=["records"])

KNOWN_ENTITY_TYPES = frozenset(REVISION_ENTITY_TYPES.values())


def serialize(revision: RecordRevision) -> dict:
    return {
        "id": revision.id,
        "patient_id": revision.patient_id,
        "entity_type": revision.entity_type,
        "entity_id": revision.entity_id,
        "revision_no": revision.revision_no,
        "action": revision.action,
        "changed_fields": revision.changed_fields or [],
        "before": revision.before,
        "after": revision.after,
        "source_kind": revision.source_kind,
        "source_ref": revision.source_ref,
        "actor_account_id": revision.actor_account_id,
        "note": revision.note,
        "created_at": revision.created_at,
    }


@router.get("/profiles/{patient_id}/revisions")
def patient_revisions(
    patient_id: str,
    entity_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """按档案回看修订历史（可选按记录类型过滤），按时间倒序。"""

    ensure_patient_access(db, principal, patient_id)
    if entity_type is not None and entity_type not in KNOWN_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"不支持的记录类型：{entity_type}")
    revisions = RecordRevisionService(db).history(
        patient_id=patient_id, entity_type=entity_type, limit=limit
    )
    return {"patient_id": patient_id, "count": len(revisions),
            "revisions": [serialize(item) for item in revisions]}


@router.get("/records/{entity_type}/{entity_id}/revisions")
def record_revisions(
    entity_type: str,
    entity_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """按单条记录回看修订历史；不可见档案的记录返回 404。"""

    if entity_type not in KNOWN_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"不支持的记录类型：{entity_type}")
    revisions = RecordRevisionService(db).history(
        entity_type=entity_type, entity_id=entity_id, limit=limit
    )
    if not revisions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有该记录的修订历史")
    patient_id = revisions[0].patient_id
    if patient_id is not None:
        ensure_patient_access(db, principal, patient_id)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "revisions": [serialize(item) for item in revisions],
    }
