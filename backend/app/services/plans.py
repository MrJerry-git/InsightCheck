"""T06/T07：三档方案服务。

* 正式接入价格目录（数据库价格记录 → ``PriceCatalog``），未知价格不冒充完整总价。
* 复用既有 ``PlanBuilder`` 完成档位组合与预算重算，不在 API 层重写费用逻辑。
* 每次编辑都重新执行规则（新增项目不能绕过禁止/暂缓结论）并生成新的修订快照；
  旧修订保持原样可回看。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AnalysisRun, ExamItem, Patient, Plan, PlanRevision
from app.models.enums import CostLevel, PlanStatus
from app.rules.models import (
    CandidateExamItem,
    ExamHistoryFact,
    LesionHistoryFact,
    RiskPredictionFact,
    RuleEvaluationRequest,
)
from app.schemas.plan_builder import (
    TIER_ORDER,
    BudgetSpec,
    CandidateRuleStatus,
    PlanBuildRequest,
    PlanCandidate,
)
from app.services.analysis.runner import AnalysisRunner, input_fingerprint
from app.services.medical_rule_service import MedicalRuleEngineService
from app.services.plan_builder import PlanBuilder
from app.services.pricing_service import load_price_catalog

PLAN_SCHEMA_VERSION = "plan-record-v1"


class PlanError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def candidate_from_analysis(item: dict[str, Any]) -> PlanCandidate:
    """把分析候选转换为方案候选；score 保持 None，不把未评估当成 0 分。"""

    note_reasons: list[str] = []
    for trace in item.get("rule_trace", []):
        if trace.get("matched") or not trace.get("enabled", True):
            note_reasons.append(f"{trace['rule_code']}: {trace['reason']}")
    evidence: list[str] = []
    for source in item.get("sources", []):
        evidence.extend(source.get("evidence_refs", []))
    return PlanCandidate(
        exam_item_id=item["exam_item_id"],
        code=item["code"],
        name=item["name"],
        category=item["category"],
        radiation=bool(item["radiation"]),
        cost_level=CostLevel(item["cost_level"]),
        score=item.get("score"),
        rule_status=CandidateRuleStatus(item.get("rule_status", "NOT_CONFIGURED")),
        rule_set_version=(item.get("rule_set_versions") or [None])[0],
        rule_notes=tuple(note_reasons[:20]),
        rule_evidence_refs=tuple(sorted(set(evidence))[:50]),
    )


class PlanService:
    def __init__(
        self,
        db: Session,
        *,
        builder: PlanBuilder | None = None,
        rules: MedicalRuleEngineService | None = None,
    ) -> None:
        self.db = db
        self.builder = builder or PlanBuilder()
        self.rules = rules or MedicalRuleEngineService(db)

    # ---- 创建 -------------------------------------------------------------
    def create(
        self,
        *,
        patient: Patient,
        analysis_run: AnalysisRun,
        tiers: tuple[Any, ...] | None = None,
        budget_limit_cents: int | None = None,
        budget_currency: str | None = None,
        institution: str | None = None,
        region: str | None = None,
        request_id: str | None = None,
        actor_account_id: str | None = None,
    ) -> Plan:
        if request_id:
            existing = self.db.scalar(select(Plan).where(Plan.request_id == request_id))
            if existing is not None:
                if existing.patient_id != patient.id:
                    raise PlanError("同一 request_id 对应不同档案", status_code=409)
                return existing
        if analysis_run.patient_id != patient.id:
            raise PlanError("分析结果不属于该档案", status_code=409)
        if self._is_stale(patient, analysis_run):
            raise PlanError("分析结果已过期，请先重新分析再生成方案", status_code=409)
        selected_tiers = tuple(tiers) if tiers else TIER_ORDER
        plan = Plan(
            patient_id=patient.id,
            analysis_run_id=analysis_run.id,
            as_of_date=analysis_run.as_of_date,
            status=PlanStatus.DRAFT,
            revision_no=0,
            budget_limit_cents=budget_limit_cents,
            budget_currency=budget_currency,
            institution=institution,
            region=region,
            request_id=request_id,
            created_by_account_id=actor_account_id,
        )
        self.db.add(plan)
        self.db.flush()
        snapshot = self._build_snapshot(
            patient=patient,
            analysis_run=analysis_run,
            as_of_date=analysis_run.as_of_date,
            candidates=[candidate_from_analysis(item) for item in analysis_run.candidates],
            manual_exclusions={},
            tiers=selected_tiers,
            budget_limit_cents=budget_limit_cents,
            budget_currency=budget_currency,
            institution=institution,
            region=region,
            reason="初始方案",
        )
        self._save_revision(
            plan, snapshot, reason="初始方案", action="create", actor_account_id=actor_account_id
        )
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def _is_stale(self, patient: Patient, run: AnalysisRun) -> bool:
        return input_fingerprint(self.db, patient, run.as_of_date) != run.input_fingerprint

    # ---- 编辑 -------------------------------------------------------------
    def edit(
        self,
        plan: Plan,
        *,
        reason: str,
        add_exam_codes: list[str] | None = None,
        remove_exam_codes: list[str] | None = None,
        budget_limit_cents: int | None = None,
        budget_currency: str | None = None,
        actor_account_id: str | None = None,
    ) -> Plan:
        if not reason.strip():
            raise PlanError("修改方案必须填写修改原因", status_code=422)
        if plan.status is PlanStatus.CONFIRMED:
            raise PlanError("已确认的方案不能直接修改，请新建方案", status_code=409)
        run = self.db.get(AnalysisRun, plan.analysis_run_id) if plan.analysis_run_id else None
        if run is None:
            raise PlanError("方案缺少分析结果，无法复算", status_code=409)
        patient = self.db.get(Patient, plan.patient_id)
        if self._is_stale(patient, run):
            raise PlanError("资料已变化，请先重新分析再修改方案", status_code=409)

        exclusion_state = dict(plan.current_snapshot.get("manual_exclusions", {}))
        candidates = {
            item["exam_item_id"]: item for item in (run.candidates or [])
        }
        removed_codes = {code.strip().upper() for code in (remove_exam_codes or [])}
        added_codes = {code.strip().upper() for code in (add_exam_codes or [])}

        for code in removed_codes:
            item = self._item_by_code(code)
            exclusion_state[item.id] = {"code": item.code, "reason": f"人工排除：{reason}"}
        for code in added_codes:
            item = self._item_by_code(code)
            if item.id in exclusion_state:
                exclusion_state.pop(item.id)
            if item.id not in candidates:
                # 新增目录项目必须重新过规则，不能因为人工加入就绕过禁止/暂缓结论。
                candidates[item.id] = self._evaluate_item(run, patient, item)
        refreshed = [
            candidate_from_analysis(item)
            for item in candidates.values()
            if item["exam_item_id"] not in exclusion_state
        ]
        snapshot = self._build_snapshot(
            patient=patient,
            analysis_run=run,
            as_of_date=plan.as_of_date,
            candidates=refreshed,
            manual_exclusions=exclusion_state,
            tiers=tuple(plan.current_snapshot.get("tiers", TIER_ORDER)),
            budget_limit_cents=(
                plan.budget_limit_cents if budget_limit_cents is None else budget_limit_cents
            ),
            budget_currency=budget_currency or plan.budget_currency,
            institution=plan.institution,
            region=plan.region,
            reason=reason,
        )
        plan.status = PlanStatus.DRAFT
        plan.budget_limit_cents = snapshot["budget"]["limit_cents"]
        plan.budget_currency = snapshot["budget"]["currency"]
        self._save_revision(
            plan, snapshot, reason=reason, action="edit", actor_account_id=actor_account_id
        )
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def _item_by_code(self, code: str) -> ExamItem:
        item = self.db.scalar(select(ExamItem).where(ExamItem.code == code))
        if item is None:
            raise PlanError(f"项目目录中没有编码 {code}", status_code=404)
        return item

    def _evaluate_item(
        self, run: AnalysisRun, patient: Patient, item: ExamItem
    ) -> dict[str, Any]:
        runner = AnalysisRunner(self.db)
        context = runner._patient_context(patient, run.as_of_date)  # noqa: SLF001
        evaluation = self.rules.evaluate(
            RuleEvaluationRequest(
                patient=context,
                exam_item=CandidateExamItem(
                    exam_item_id=item.id,
                    code=item.code,
                    name=item.name,
                    category=item.category,
                    radiation=item.radiation,
                ),
                deepfm_score=0.0,
                risk_predictions=[
                    RiskPredictionFact(
                        risk_code=row.risk_code,
                        probability=row.probability,
                        model_version=row.risk_model_version,
                        evidence_refs=[row.id],
                    )
                    for row in patient.risk_predictions
                ],
                exam_history=[
                    ExamHistoryFact(
                        exam_item_id=history.exam_item_id,
                        exam_code=history.exam_item.code,
                        performed_at=check.check_date,
                        result_status=history.result_status.value,
                        radiation=history.exam_item.radiation,
                        evidence_refs=[history.id],
                    )
                    for check in patient.health_checks
                    if check.check_date <= run.as_of_date
                    for history in check.exam_histories
                ],
                lesion_history=[
                    LesionHistoryFact(
                        lesion_type=track.lesion_type,
                        location=track.location,
                        last_exam_date=max(
                            observation.exam_date for observation in track.observations
                        ),
                        match_status=track.observations[-1].match_status.value,
                        growing=None,
                        evidence_refs=[],
                    )
                    for track in patient.lesion_tracks
                    if track.observations
                ],
                trace_id=run.id,
            )
        )
        status = CandidateRuleStatus.from_rule_evaluation(evaluation)
        if status.forbids_selection:
            raise PlanError(
                f"项目 {item.code} 命中禁止或暂缓规则，不能人工加入方案", status_code=409
            )
        return {
            "exam_item_id": item.id,
            "code": item.code,
            "name": item.name,
            "category": item.category,
            "radiation": item.radiation,
            "cost_level": item.cost_level.value,
            "score": None,
            "model_status": "未评估：尚无经验证的适用模型",
            "rule_status": status.value,
            "decision": (
                "include" if status is CandidateRuleStatus.ALLOWED else "require_review"
            ),
            "sources": [],
            "system": item.category,
            "missing_information": ["人工加入目录项目：需人工确认必要性"],
            "conflicts": [],
            "rule_set_versions": sorted(
                {record.version for record in evaluation.execution_trace}
            ),
            "rule_trace": [
                {
                    "rule_code": record.rule_code,
                    "version": record.version,
                    "enabled": record.enabled,
                    "matched": record.matched,
                    "reason": record.reason,
                }
                for record in evaluation.execution_trace
            ],
            "disclosures": ["人工加入的项目仍需人工复核。"],
        }

    # ---- 状态流转 ---------------------------------------------------------
    def submit_review(self, plan: Plan, *, actor_account_id: str | None = None) -> Plan:
        if plan.status is not PlanStatus.DRAFT:
            raise PlanError("只有草稿方案可以提交审核", status_code=409)
        plan.status = PlanStatus.REVIEW
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def confirm_plan(self, plan: Plan, *, actor_account_id: str | None = None) -> Plan:
        if plan.status is not PlanStatus.REVIEW:
            raise PlanError("只有待审核方案可以确认", status_code=409)
        if any(
            item["rule_status"] == "BLOCKED"
            for tier in plan.current_snapshot.get("tiers_result", [])
            for item in tier.get("items", [])
        ):
            raise PlanError("方案中存在被规则禁止的项目，不能确认", status_code=409)
        plan.status = PlanStatus.CONFIRMED
        self.db.commit()
        self.db.refresh(plan)
        return plan

    # ---- 修订 -------------------------------------------------------------
    def revisions(self, plan: Plan, *, limit: int = 50) -> list[PlanRevision]:
        return list(
            self.db.scalars(
                select(PlanRevision)
                .where(PlanRevision.plan_id == plan.id)
                .order_by(PlanRevision.revision_no.desc())
                .limit(limit)
            )
        )

    def revision(self, plan: Plan, revision_no: int) -> PlanRevision:
        row = self.db.scalar(
            select(PlanRevision).where(
                PlanRevision.plan_id == plan.id, PlanRevision.revision_no == revision_no
            )
        )
        if row is None:
            raise PlanError("方案修订不存在", status_code=404)
        return row

    # ---- 内部 -------------------------------------------------------------
    def _save_revision(
        self,
        plan: Plan,
        snapshot: dict[str, Any],
        *,
        reason: str,
        action: str,
        actor_account_id: str | None,
    ) -> PlanRevision:
        revision_no = (
            self.db.scalar(
                select(func.max(PlanRevision.revision_no)).where(
                    PlanRevision.plan_id == plan.id
                )
            )
            or 0
        ) + 1
        revision = PlanRevision(
            plan_id=plan.id,
            revision_no=revision_no,
            reason=reason,
            action=action,
            analysis_run_id=plan.analysis_run_id,
            price_catalog_version=snapshot["price_catalog_version"],
            snapshot=snapshot,
            created_by_account_id=actor_account_id,
        )
        self.db.add(revision)
        plan.revision_no = revision_no
        plan.current_snapshot = snapshot
        plan.price_catalog_version = snapshot["price_catalog_version"]
        plan.budget_limit_cents = snapshot["budget"]["limit_cents"]
        plan.budget_currency = snapshot["budget"]["currency"]
        return revision

    def _build_snapshot(
        self,
        *,
        patient: Patient,
        analysis_run: AnalysisRun,
        as_of_date: date,
        candidates: list[PlanCandidate],
        manual_exclusions: dict[str, Any],
        tiers: tuple[Any, ...],
        budget_limit_cents: int | None,
        budget_currency: str | None,
        institution: str | None,
        region: str | None,
        reason: str,
    ) -> dict[str, Any]:
        catalog = load_price_catalog(
            self.db, as_of_date=as_of_date, institution=institution, region=region
        )
        budget = (
            BudgetSpec(
                limit_cents=budget_limit_cents,
                currency=(budget_currency or "CNY"),
                note=f"方案预算：{reason}"[:300],
            )
            if budget_limit_cents is not None
            else None
        )
        request = PlanBuildRequest(
            trace_id=analysis_run.id,
            patient_id=patient.id,
            as_of_date=as_of_date,
            candidates=tuple(candidates),
            price_catalog=catalog,
            budget=budget,
            institution=institution,
            region=region,
            tiers=tuple(tiers),
        )
        result = self.builder.build(request)
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "plan_reason": reason,
            "analysis_run_id": analysis_run.id,
            "analysis_fingerprint": analysis_run.input_fingerprint,
            "patient_id": patient.id,
            "as_of_date": as_of_date.isoformat(),
            "tiers": [tier.tier.value for tier in result.tiers],
            "price_catalog_version": result.price_catalog_version,
            "rule_set_versions": list(result.rule_set_versions),
            "budget": {
                "limit_cents": budget_limit_cents,
                "currency": (budget_currency or ("CNY" if budget_limit_cents else None)),
            },
            "manual_exclusions": manual_exclusions,
            "tiers_result": [tier.model_dump(mode="json") for tier in result.tiers],
            "notes": list(result.notes),
            "disclosures": list(result.disclosures),
        }

    # ---- 展示 -------------------------------------------------------------
    def serialize(self, plan: Plan, *, include_snapshot: bool = True) -> dict[str, Any]:
        run = self.db.get(AnalysisRun, plan.analysis_run_id) if plan.analysis_run_id else None
        patient = self.db.get(Patient, plan.patient_id)
        stale = bool(run is not None and patient is not None and self._is_stale(patient, run))
        payload: dict[str, Any] = {
            "plan_id": plan.id,
            "patient_id": plan.patient_id,
            "analysis_run_id": plan.analysis_run_id,
            "as_of_date": plan.as_of_date,
            "status": plan.status.value,
            "revision_no": plan.revision_no,
            "price_catalog_version": plan.price_catalog_version,
            "budget": plan.current_snapshot.get("budget", {}),
            "institution": plan.institution,
            "region": plan.region,
            "created_at": plan.created_at,
            "stale": stale,
            "stale_reason": "资料已更新，方案基于旧版本分析" if stale else None,
            "notes": plan.current_snapshot.get("notes", []),
            "disclosures": plan.current_snapshot.get("disclosures", []),
        }
        if include_snapshot:
            payload["tiers"] = plan.current_snapshot.get("tiers_result", [])
            payload["manual_exclusions"] = plan.current_snapshot.get("manual_exclusions", {})
        return payload
