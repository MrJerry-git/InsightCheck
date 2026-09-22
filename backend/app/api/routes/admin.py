"""T08：管理 API（字典映射、价格生效范围、规则生命周期、模型状态与审计）。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_db, require_admin
from app.features.metric_normalizer import MetricNormalizer
from app.models import (
    ExamItem,
    ExamItemPriceRecord,
    LabMetric,
    MedicalRule,
    MetricDictionary,
)
from app.models.enums import NormalizationStatus
from app.rules.models import RuleAction, RuleType
from app.schemas.domain import MetricNormalizationRequest
from app.services.audit import AuditService
from app.services.model_status import model_task_status
from app.services.record_revisions import RecordRevisionService

router = APIRouter(prefix="/admin", tags=["admin"])


class MetricMapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mappings: list[dict] = Field(min_length=1, max_length=200)


class PriceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exam_item_code: str = Field(min_length=1, max_length=64)
    amount_cents: int = Field(ge=0)
    currency: str = Field(default="CNY", max_length=3)
    source: str = Field(min_length=1, max_length=300)
    source_url: str | None = Field(default=None, max_length=500)
    institution: str | None = Field(default=None, max_length=200)
    region: str | None = Field(default=None, max_length=100)
    effective_from: date
    effective_to: date | None = None
    is_demo_price: bool = False
    note: str | None = None


class PriceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_cents: int | None = Field(default=None, ge=0)
    effective_to: date | None = None
    note: str | None = None


class RuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_code: str = Field(min_length=1, max_length=100)
    rule_type: RuleType
    exam_item_code: str | None = Field(default=None, max_length=64)
    condition: dict
    action: RuleAction
    priority: int = Field(default=0, ge=0)
    source: str = Field(min_length=1, max_length=300)
    version: str = Field(min_length=1, max_length=64)
    enabled: bool = False


class RuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, min_length=1, max_length=300)


def audit(db: Session, principal: Principal, **kwargs) -> None:
    AuditService(db).record(
        actor_account_id=principal.account_id, actor_username=principal.username, **kwargs
    )


# ---- 字典映射 -------------------------------------------------------------
@router.get("/metric-mapping-queue")
def mapping_queue(
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """待映射队列：导入时未命中目录的指标保留原文，等待人工映射。"""

    metrics = db.scalars(
        select(LabMetric)
        .where(LabMetric.metric_code == "UNMAPPED")
        .order_by(LabMetric.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "metric_id": metric.id,
            "health_check_id": metric.health_check_id,
            "original_name": metric.original_name,
            "original_value": metric.original_value,
            "original_unit": metric.original_unit,
            "source_kind": metric.source_kind,
            "source_ref": metric.source_ref,
            "created_at": metric.created_at,
        }
        for metric in metrics
    ]


@router.post("/metric-mapping")
def apply_mapping(
    payload: MetricMapRequest,
    principal: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """把待映射指标改绑到目录编码；目录里没有的编码不自动创建。"""

    definitions = {
        item.metric_code: item for item in db.scalars(select(MetricDictionary)).all()
    }
    normalizer = MetricNormalizer(definitions.values())
    revisions = RecordRevisionService(db)
    results: list[dict] = []
    pending: list[dict] = []
    try:
        for entry in payload.mappings:
            metric = db.get(LabMetric, entry.get("metric_id"))
            code = str(entry.get("metric_code", "")).strip().upper()
            if metric is None:
                raise HTTPException(status_code=404, detail=f"指标不存在：{entry.get('metric_id')}")
            definition = definitions.get(code)
            if definition is None:
                raise HTTPException(status_code=422, detail=f"目录中没有编码 {code}")
            before = {
                "metric_code": metric.metric_code,
                "canonical_name": metric.canonical_name,
                "original_unit": metric.original_unit,
                "standard_unit": metric.standard_unit,
                "value": metric.value,
            }
            # 复用有依据的标准化逻辑：只有命中字典登记的换算依据才改写数值与单位，
            # 否则保持待确认，绝不把原单位标签直接换成标准单位（审核 P1）。
            normalized = normalizer.normalize(
                MetricNormalizationRequest(
                    original_name=definition.metric_code,
                    original_value=metric.original_value,
                    original_unit=metric.original_unit,
                    reference_min=metric.reference_min,
                    reference_max=metric.reference_max,
                )
            )
            metric.normalization_status = normalized.normalization_status
            metric.normalization_version = normalized.normalization_version
            if normalized.normalization_status is not NormalizationStatus.NORMALIZED:
                db.flush()
                revisions.record(
                    metric,
                    action="update",
                    before=before,
                    source_kind="manual",
                    source_ref="admin:metric-mapping",
                    actor_account_id=principal.account_id,
                    note="管理员人工映射未通过标准化校验，保持待确认",
                )
                pending.append(
                    {
                        "metric_id": metric.id,
                        "requested_metric_code": definition.metric_code,
                        "reason": "；".join(normalized.issues) or "单位/数值无法确认",
                        "normalization_status": normalized.normalization_status.value,
                    }
                )
                continue
            metric.metric_code = definition.metric_code
            metric.canonical_name = definition.canonical_name
            metric.value = normalized.value
            metric.standard_unit = normalized.standard_unit
            metric.reference_min = normalized.reference_min
            metric.reference_max = normalized.reference_max
            db.flush()
            revisions.record(
                metric,
                action="update",
                before=before,
                source_kind="manual",
                source_ref="admin:metric-mapping",
                actor_account_id=principal.account_id,
                note="管理员人工映射",
            )
            results.append(
                {
                    "metric_id": metric.id,
                    "metric_code": definition.metric_code,
                    "original_unit": before["original_unit"],
                    "standard_unit": metric.standard_unit,
                    "value_before": before["value"],
                    "value_after": metric.value,
                }
            )
        audit(
            db,
            principal,
            action="metric.mapped",
            entity_type="lab_metric",
            summary=(
                f"人工映射 {len(results)} 条待映射指标"
                + (f"，{len(pending)} 条因单位/数值无法确认保持待确认" if pending else "")
            ),
            payload={"count": len(results), "pending_count": len(pending)},
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return {"mapped": results, "pending": pending}


# ---- 价格生效范围 ---------------------------------------------------------
@router.get("/exam-item-prices")
def list_prices(
    exam_item_code: str | None = Query(default=None),
    as_of_date: date | None = Query(default=None),  # noqa: B008
    _: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    statement = (
        select(ExamItemPriceRecord, ExamItem.code)
        .join(ExamItem, ExamItem.id == ExamItemPriceRecord.exam_item_id)
        .order_by(ExamItem.code, ExamItemPriceRecord.effective_from.desc())
    )
    if exam_item_code:
        statement = statement.where(ExamItem.code == exam_item_code.strip().upper())
    if as_of_date is not None:
        statement = statement.where(ExamItemPriceRecord.effective_from <= as_of_date).where(
            ExamItemPriceRecord.effective_to.is_(None)
            | (ExamItemPriceRecord.effective_to >= as_of_date)
        )
    rows = db.execute(statement).all()
    return [
        {
            "price_id": record.id,
            "exam_item_code": code,
            "amount_cents": record.amount_cents,
            "currency": record.currency,
            "source": record.source,
            "source_url": record.source_url,
            "institution": record.institution,
            "region": record.region,
            "effective_from": record.effective_from,
            "effective_to": record.effective_to,
            "is_demo_price": record.is_demo_price,
            "note": record.note,
        }
        for record, code in rows
    ]


@router.post("/exam-item-prices", status_code=status.HTTP_201_CREATED)
def create_price(
    payload: PriceCreate,
    principal: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """登记价格：真实价格必须带来源链接与来源说明，演示价必须显式标记。"""

    item = db.scalar(
        select(ExamItem).where(ExamItem.code == payload.exam_item_code.strip().upper())
    )
    if item is None:
        raise HTTPException(status_code=404, detail="体检项目不存在")
    if not payload.is_demo_price and not payload.source_url:
        raise HTTPException(status_code=422, detail="真实价格必须提供来源链接")
    if payload.effective_to is not None and payload.effective_to < payload.effective_from:
        raise HTTPException(status_code=422, detail="失效日期不能早于生效日期")
    record = ExamItemPriceRecord(
        exam_item_id=item.id,
        amount_cents=payload.amount_cents,
        currency=payload.currency.upper(),
        source=payload.source,
        source_url=payload.source_url,
        institution=payload.institution,
        region=payload.region,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        is_demo_price=payload.is_demo_price,
        note=payload.note,
    )
    db.add(record)
    audit(
        db,
        principal,
        action="price.created",
        entity_type="exam_item_price",
        entity_id=item.code,
        summary=f"登记价格 {item.code} {payload.amount_cents} 分（{payload.currency}）",
        payload={"effective_from": str(payload.effective_from), "is_demo": payload.is_demo_price},
    )
    db.commit()
    db.refresh(record)
    return {"price_id": record.id}


@router.patch("/exam-item-prices/{price_id}")
def update_price(
    price_id: str,
    payload: PriceUpdate,
    principal: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    record = db.get(ExamItemPriceRecord, price_id)
    if record is None:
        raise HTTPException(status_code=404, detail="价格记录不存在")
    before = {
        "amount_cents": record.amount_cents,
        "effective_to": str(record.effective_to) if record.effective_to else None,
    }
    if payload.amount_cents is not None:
        record.amount_cents = payload.amount_cents
    if payload.effective_to is not None:
        if payload.effective_to < record.effective_from:
            raise HTTPException(status_code=422, detail="失效日期不能早于生效日期")
        record.effective_to = payload.effective_to
    if payload.note is not None:
        record.note = payload.note
    audit(
        db,
        principal,
        action="price.updated",
        entity_type="exam_item_price",
        entity_id=record.id,
        summary="更新价格记录",
        payload={"before": before},
    )
    db.commit()
    return {"price_id": record.id, "amount_cents": record.amount_cents}


# ---- 规则生命周期 ---------------------------------------------------------
@router.get("/rules")
def list_rules(
    rule_code: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    _: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    statement = select(MedicalRule).order_by(
        MedicalRule.rule_code, MedicalRule.version.desc()
    )
    if rule_code:
        statement = statement.where(MedicalRule.rule_code == rule_code)
    if enabled is not None:
        statement = statement.where(MedicalRule.enabled == enabled)
    return [
        {
            "rule_id": rule.id,
            "rule_code": rule.rule_code,
            "rule_type": rule.rule_type,
            "version": rule.version,
            "action": rule.action.value,
            "priority": rule.priority,
            "enabled": rule.enabled,
            "source": rule.source,
            "exam_item_id": rule.exam_item_id,
            "condition": rule.condition_json,
        }
        for rule in db.scalars(statement).all()
    ]


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: RuleCreate,
    principal: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """新增规则或新版本；默认以草稿（enabled=false）保存，避免影响线上结果。"""

    existing = db.scalar(
        select(MedicalRule).where(
            MedicalRule.rule_code == payload.rule_code,
            MedicalRule.version == payload.version,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="同编码同版本规则已存在")
    exam_item_id = None
    if payload.exam_item_code:
        item = db.scalar(
            select(ExamItem).where(ExamItem.code == payload.exam_item_code.strip().upper())
        )
        if item is None:
            raise HTTPException(status_code=404, detail="体检项目不存在")
        exam_item_id = item.id
    rule = MedicalRule(
        rule_code=payload.rule_code,
        rule_type=payload.rule_type.value,
        exam_item_id=exam_item_id,
        condition_json=payload.condition,
        action=payload.action,
        priority=payload.priority,
        source=payload.source,
        version=payload.version,
        enabled=payload.enabled,
    )
    db.add(rule)
    audit(
        db,
        principal,
        action="rule.created",
        entity_type="medical_rule",
        entity_id=payload.rule_code,
        summary=f"新增规则版本 {payload.rule_code}@{payload.version}（enabled={payload.enabled}）",
        payload={"action": payload.action.value},
    )
    db.commit()
    db.refresh(rule)
    return {"rule_id": rule.id, "enabled": rule.enabled}


@router.patch("/rules/{rule_id}")
def update_rule(
    rule_id: str,
    payload: RuleUpdate,
    principal: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    rule = db.get(MedicalRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    before = {"enabled": rule.enabled, "priority": rule.priority}
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    if payload.priority is not None:
        rule.priority = payload.priority
    if payload.source is not None:
        rule.source = payload.source
    audit(
        db,
        principal,
        action="rule.updated",
        entity_type="medical_rule",
        entity_id=rule.rule_code,
        summary=f"更新规则 {rule.rule_code}@{rule.version}",
        payload={"before": before},
    )
    db.commit()
    return {"rule_id": rule.id, "enabled": rule.enabled, "priority": rule.priority}


# ---- 模型任务状态 ---------------------------------------------------------
@router.get("/model-tasks")
def model_tasks(
    _: Principal = Depends(require_admin),  # noqa: B008
):
    """模型任务注册状态：明确区分已接入/未接入，不把接口预留当成已接入。"""

    status = model_task_status()
    artifact = status["artifact"]
    ranking = status["ranking"]
    artifact_labels = {
        "unconfigured": "未接入",
        "missing_file": "制品缺失",
        "load_error": "制品无法加载",
        "loadable": "制品可加载",
    }
    return {
        "provider_version": "local-rules-v1",
        "registry_version": status["registry_version"],
        "artifact": artifact,
        "tasks": [
            {
                "task": "disease_risk_models",
                "name": "各疾病风险模型",
                "status": "未接入",
                "detail": "本轮只提供任务注册与未接入显示；标签与随访数据到达后再训练",
                "owner": "王宏锦（王天一接入、陈子正展示）",
            },
            {
                "task": "deepfm_ranking",
                "name": "DeepFM 学习排序",
                "status": artifact_labels[artifact["state"]],
                "detail": (
                    f"{artifact['detail']}；H09 注册表状态 {ranking['registry_status']}"
                    + (
                        f"（{ranking['unavailable_reason']}）"
                        if ranking["unavailable_reason"]
                        else ""
                    )
                ),
                "artifact_state": artifact["state"],
                "registry_status": ranking["registry_status"],
                "available": ranking["available"],
                "unavailable_reason": ranking["unavailable_reason"],
                "owner": "王宏锦",
            },
            {
                "task": "report_extraction",
                "name": "本机构报告适配/抽取优化",
                "status": "部分接入",
                "detail": "已接入本机 Qwen 与表格解析；真实版式质量待 H04 对照调整",
                "owner": "王宏锦；陈子正校对交互",
            },
            {
                "task": "lesion_matching",
                "name": "病灶匹配及模型效果",
                "status": "部分接入",
                "detail": "病灶跟踪流程可用；匹配质量需核验集评估后才能报告",
                "owner": "王宏锦",
            },
            {
                "task": "llm_qa",
                "name": "语言模型问答",
                "status": "未接入",
                "detail": "问答接口已就绪，模型服务由 H08 提供；未接入时返回结构化回答",
                "owner": "王宏锦（王天一接线）",
            },
        ],
    }


# ---- 审计 -----------------------------------------------------------------
@router.get("/audit")
def audit_events(
    source: str = Query(default="all", pattern="^(all|admin|records|plans)$"),
    patient_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    return {
        "source": source,
        "events": AuditService(db).combined(
            limit=limit, source=source, patient_id=patient_id
        ),
    }
