import json
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    Principal,
    ensure_patient_access,
    get_current_principal,
    get_db,
    require_write_access,
    scope_patient_statement,
)
from app.models import (
    AIReport,
    ExamItem,
    HealthCheck,
    LabMetric,
    MetricDictionary,
    Patient,
    Recommendation,
    RecommendationItem,
)
from app.models.enums import (
    AIReportType,
    MetricStatus,
    NormalizationStatus,
    PlanTier,
    RecommendationDecision,
    RecommendationStatus,
)
from app.rules.models import (
    CandidateExamItem,
    ExamHistoryFact,
    PatientContext,
    RuleEvaluationRequest,
)
from app.services.medical_rule_service import MedicalRuleEngineService
from app.services.record_revisions import RecordRevisionService
from app.services.seed_service import DemoSeedService
from app.services.workflow_models import VERSION, predict

router = APIRouter(prefix="/workflow", tags=["1.0 workflow"])


class MetricInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    code: str = Field(min_length=1, max_length=64)
    value: float


class RecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: str
    check_date: date
    is_demo: bool = False
    metrics: list[MetricInput] = Field(min_length=1, max_length=100)


@router.post("/records")
def record(
    payload: RecordInput,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    patient = ensure_patient_access(db, principal, payload.patient_id)
    if payload.check_date > date.today() or (
        patient.birth_date and payload.check_date < patient.birth_date
    ):
        raise HTTPException(422, "记录日期应在出生日期与今天之间")
    if len({m.code for m in payload.metrics}) != len(payload.metrics):
        raise HTTPException(422, "同一记录不能重复填写相同指标")
    definitions = {d.metric_code: d for d in db.scalars(select(MetricDictionary)).all()}
    if any(m.code not in definitions for m in payload.metrics):
        raise HTTPException(422, "存在未配置字典的指标")
    for metric in payload.metrics:
        definition = definitions[metric.code]
        if (definition.valid_min is not None and metric.value < definition.valid_min) or (
            definition.valid_max is not None and metric.value > definition.valid_max
        ):
            raise HTTPException(422, "指标数值超出字典允许范围，请核对数值与单位")
    check = HealthCheck(
        patient_id=patient.id,
        check_date=payload.check_date,
        is_demo=payload.is_demo,
        institution="工作台手工录入",
        source_kind="manual",
        source_ref="workflow/records",
    )
    try:
        db.add(check)
        db.flush()
        revisions = RecordRevisionService(db)
        revisions.record(check, action="create", actor_account_id=principal.account_id)
        for metric in payload.metrics:
            d = definitions[metric.code]
            metric_row = LabMetric(
                health_check_id=check.id,
                metric_code=metric.code,
                original_name=d.canonical_name,
                canonical_name=d.canonical_name,
                original_value=str(metric.value),
                value=metric.value,
                original_unit=d.standard_unit,
                standard_unit=d.standard_unit,
                status=MetricStatus.UNKNOWN,
                normalization_status=NormalizationStatus.NORMALIZED,
                normalization_version="manual-standard-unit-v1",
                value_type=d.value_type,
                source_kind="manual",
                source_ref="workflow/records",
            )
            db.add(metric_row)
            db.flush()
            revisions.record(metric_row, action="create", actor_account_id=principal.account_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"id": check.id}


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    patient_id: str
    as_of_date: date
    tier: PlanTier = PlanTier.STANDARD


def owned_plan(db: Session, principal: Principal, plan_id: str) -> dict:
    """读取方案快照前先按快照所属档案校验权限。"""

    recommendation = db.get(Recommendation, plan_id)
    if recommendation is not None:
        ensure_patient_access(db, principal, recommendation.patient_id)
    return saved(db, plan_id)


@router.post("/demo")
def demo(
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):  # noqa: B008
    DemoSeedService(db).run()
    patient = db.scalar(
        scope_patient_statement(
            select(Patient).where(Patient.anonymous_code == DemoSeedService.PATIENT_CODE), principal
        )
    )
    if patient is None:
        raise HTTPException(404, "演示档案不存在或无权访问")
    return {"patient_id": patient.id}


@router.get("/patients")
def patients(
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    return [
        {
            "id": p.id,
            "code": p.anonymous_code,
            "gender": p.gender,
            "birth_date": p.birth_date,
            "checks": len(p.health_checks),
        }
        for p in db.scalars(
            scope_patient_statement(
                select(Patient).order_by(Patient.anonymous_code), principal
            )
        ).all()
    ]


@router.get("/patients/{patient_id}")
def detail(
    patient_id: str,
    as_of_date: date | None = None,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """档案历史与趋势；调用前先校验档案归属。"""

    patient = ensure_patient_access(db, principal, patient_id)
    return patient_detail(db, patient, as_of_date)


def patient_detail(db: Session, patient: Patient, as_of_date: date | None = None) -> dict:
    """构造档案历史、趋势与病灶跟踪；按检查日期截断，不推断未来数据。"""

    cutoff = as_of_date or date.today()
    checks = sorted(
        (c for c in patient.health_checks if c.check_date <= cutoff),
        key=lambda c: (c.check_date, c.id),
    )
    trends = {}
    history = []
    for check in checks:
        metrics = []
        for m in check.lab_metrics:
            observation = {
                "id": m.id,
                "name": m.canonical_name,
                "code": m.metric_code,
                "value": m.value,
                "unit": m.standard_unit,
                "date": str(check.check_date),
                "status": m.status,
            }
            metrics.append(observation)
            trends.setdefault(m.metric_code, []).append(observation)
        images = [
            {
                "id": i.id,
                "date": str(i.exam_date),
                "type": i.exam_type,
                "report": i.report_text,
                "lesions": [
                    {
                        "id": lesion.id,
                        "location": lesion.location,
                        "size_mm": lesion.size_mm,
                        "type": lesion.lesion_type,
                    }
                    for lesion in i.lesions
                ],
            }
            for i in check.imaging_exams
            if i.exam_date <= cutoff
        ]
        history.append(
            {
                "id": check.id,
                "date": str(check.check_date),
                "is_demo": check.is_demo,
                "institution": check.institution,
                "metrics": metrics,
                "images": images,
            }
        )
    tracks = [
        {
            "id": t.id,
            "location": t.location,
            "observations": [
                {"date": str(o.exam_date), "size_mm": o.size_mm, "status": o.match_status}
                for o in sorted(t.observations, key=lambda o: o.exam_date)
                if o.exam_date <= cutoff
            ],
        }
        for t in patient.lesion_tracks
        if t.first_seen <= cutoff
    ]
    return {
        "patient_id": patient.id,
        "code": patient.anonymous_code,
        "as_of_date": str(cutoff),
        "checks": history,
        "trends": trends,
        "tracks": tracks,
        "source_kind": "synthetic" if checks and all(c.is_demo for c in checks) else "unverified",
        "availability": "检查日期截断；报告可获得时间未知，不用于正式前瞻验证",
    }


def saved(db, plan_id):
    report = db.scalar(
        select(AIReport).where(
            AIReport.recommendation_id == plan_id, AIReport.prompt_version == VERSION
        )
    )
    if not report:
        raise HTTPException(404, "未找到工作台方案快照")
    return json.loads(report.content)


@router.get("/plans")
def plans(
    patient_id: str,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    ensure_patient_access(db, principal, patient_id)
    return [
        {
            "id": r.recommendation_id,
            "created_at": r.created_at,
            "summary": json.loads(r.content)["summary"],
        }
        for r in db.scalars(
            select(AIReport)
            .where(AIReport.patient_id == patient_id, AIReport.prompt_version == VERSION)
            .order_by(AIReport.created_at.desc())
        ).all()
    ]


@router.get("/plans/{plan_id}")
def get_plan(
    plan_id: str,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    return owned_plan(db, principal, plan_id)


@router.get("/plans/{plan_id}/export")
def export_plan(
    plan_id: str,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    snapshot = owned_plan(db, principal, plan_id)
    return Response(
        content=json.dumps(snapshot, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="InsightCheck-{snapshot["id"]}.json"'
        },
    )


@router.post("/plans")
def generate(
    request: PlanRequest,
    principal: Principal = Depends(require_write_access),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    plan_id = str(request.request_id)
    if db.get(Recommendation, plan_id):
        snapshot = saved(db, plan_id)
        if snapshot["request"] != request.model_dump(mode="json"):
            raise HTTPException(409, "同一请求编号对应不同输入")
        return snapshot
    patient = ensure_patient_access(db, principal, request.patient_id)
    if request.as_of_date > date.today():
        raise HTTPException(422, "分析日期不能晚于今天")
    history = patient_detail(db, patient, request.as_of_date)
    if not history["checks"]:
        raise HTTPException(422, "所选日期之前没有体检记录，请先导入或录入")
    items = db.scalars(select(ExamItem).order_by(ExamItem.code)).all()
    if not items:
        raise HTTPException(422, "项目目录为空，请先创建演示案例或维护目录")
    age = None
    if patient.birth_date:
        age = (
            request.as_of_date.year
            - patient.birth_date.year
            - (
                (request.as_of_date.month, request.as_of_date.day)
                < (patient.birth_date.month, patient.birth_date.day)
            )
        )
    is_demo = history["source_kind"] == "synthetic"
    probability, scores = None, {}
    risk_status = "未评估：尚无经验证的适用模型"
    if is_demo and age is not None and 18 <= age <= 84:
        catalog = tuple((i.id, i.code, i.category, i.radiation, i.cost_level.value) for i in items)
        try:
            probability, scores = predict(
                catalog, patient.id, age, len(history["checks"]), request.as_of_date, plan_id
            )
            risk_status = "合成任务概率；非疾病风险。LightGBM 与 DeepFM 工程演示"
        except ImportError:
            risk_status = "未评估：需安装 research 可选依赖后运行合成模型"
    result_items = []
    service = MedicalRuleEngineService(db)
    for item in items:
        score = scores.get(item.id)
        evaluation = service.evaluate(
            RuleEvaluationRequest(
                patient=PatientContext(
                    patient_id=patient.id,
                    as_of_date=request.as_of_date,
                    age=age if age is not None and 0 <= age <= 130 else None,
                    sex=patient.gender.value,
                ),
                exam_item=CandidateExamItem(
                    exam_item_id=item.id,
                    code=item.code,
                    name=item.name,
                    category=item.category,
                    radiation=item.radiation,
                ),
                deepfm_score=score or 0.0,
                exam_history=[
                    ExamHistoryFact(
                        exam_item_id=h.exam_item_id,
                        exam_code=h.exam_item.code,
                        performed_at=c.check_date,
                        result_status=h.result_status.value,
                        radiation=h.exam_item.radiation,
                        evidence_refs=[c.id],
                    )
                    for c in patient.health_checks
                    if c.check_date <= request.as_of_date
                    for h in c.exam_histories
                ],
                trace_id=plan_id,
            )
        )
        configured = any(r.enabled for r in evaluation.execution_trace)
        status = evaluation.final_status.value if configured else "NOT_CONFIGURED"
        # A synthetic exercise never certifies clinical necessity or approval.
        group = "暂缓/不适用" if status in {"BLOCKED", "DEFERRED"} else "需复核"
        if is_demo and score is not None and not item.radiation and status == "NOT_CONFIGURED":
            group = "可选（演示）"
        result_items.append(
            {
                "id": item.id,
                "name": item.name,
                "code": item.code,
                "score": score,
                "group": group,
                "rule_status": status,
                "radiation": item.radiation,
                "cost": "未知",
                "rules": evaluation.model_dump(mode="json"),
                "reason": "未配置临床规则，不代表审核通过"
                if not configured
                else "依据已配置规则输出；需核对规则适用性",
            }
        )
    result_items.sort(key=lambda i: (-(i["score"] or 0), i["code"]))
    for index, item in enumerate(result_items, 1):
        item["rank"] = index
    summary = (
        f"{patient.anonymous_code} · {request.as_of_date} · {len(result_items)} 个候选项目待复核"
    )
    snapshot = {
        "id": plan_id,
        "request": request.model_dump(mode="json"),
        "summary": summary,
        "source_kind": history["source_kind"],
        "risk": {
            "probability": probability,
            "status": risk_status,
            "version": VERSION if probability is not None else None,
        },
        "items": result_items,
        "history": history,
        "status": "draft",
        "explanation": "根据所选日期之前的记录生成。所有项目均为方案草稿；"
        "必要项目尚无已审核依据，费用未知。当前输出统一草稿，档位差异待配置。",
        "explanation_provider": "本地结构化模板（未使用大语言模型）",
        "version": VERSION,
    }
    try:
        recommendation = Recommendation(
            id=plan_id,
            patient_id=patient.id,
            plan_tier=request.tier,
            status=RecommendationStatus.DRAFT,
            trace_id=plan_id,
            is_demo=is_demo,
            as_of_health_check_id=history["checks"][-1]["id"],
            feature_pipeline_version=VERSION,
            risk_model_version=VERSION if probability is not None else None,
            recommendation_model_version=VERSION if scores else None,
        )
        db.add(recommendation)
        db.flush()
        for item in result_items:
            db.add(
                RecommendationItem(
                    recommendation_id=plan_id,
                    exam_item_id=item["id"],
                    model_score=item["score"],
                    decision=RecommendationDecision.REQUIRE_REVIEW,
                    rank=item["rank"],
                    explanation=item["reason"],
                    applied_rules=item["rules"]["execution_trace"],
                )
            )
        db.add(
            AIReport(
                patient_id=patient.id,
                recommendation_id=plan_id,
                report_type=AIReportType.RECOMMENDATION_EXPLANATION,
                content=json.dumps(snapshot, ensure_ascii=False),
                llm_model="local-template",
                prompt_version=VERSION,
                source_trace_id=plan_id,
                is_demo=is_demo,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.get(Recommendation, plan_id):
            snapshot = saved(db, plan_id)
            if snapshot["request"] == request.model_dump(mode="json"):
                return snapshot
        raise HTTPException(409, "方案保存冲突，请重新加载后重试") from None
    except Exception:
        db.rollback()
        raise
    return snapshot


class Question(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@router.post("/plans/{plan_id}/explain")
def explain(
    plan_id: str,
    question: Question,
    principal: Principal = Depends(get_current_principal),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    snapshot = owned_plan(db, principal, plan_id)
    if any(word in question.text for word in ("风险", "概率", "模型")):
        answer = snapshot["risk"]["status"]
    elif any(word in question.text for word in ("价格", "费用", "多少钱")):
        answer = "尚未接入真实价格，当前无法计算总费用。"
    elif any(word in question.text for word in ("数据", "记录", "来源")):
        answer = (
            f"来源：{snapshot['source_kind']}；包含 {len(snapshot['history']['checks'])} 次记录。"
        )
    else:
        answer = snapshot["explanation"]
    return {"answer": answer, "provider": "本地方案说明（非开放式医学问答）", "trace_id": plan_id}
