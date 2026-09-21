"""分析编排（T04）与跨系统候选汇总（T05）。

* 固定决策日期与输入版本：结果可复现，资料变化后旧结果标记过期而不是被改写。
* 候选来自体检项目目录；疾病模型未接入时返回“未评估”，不产生虚构概率。
* 跨系统去重：多个发现指向同一检查项目时只计一次，理由与证据合并保留。
* 规则结论、禁止/暂缓/冲突/待复核全部来自规则引擎执行轨迹，可追踪。
"""

from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisRun,
    ExamHistory,
    ExamItem,
    HealthCheck,
    LesionObservation,
    LesionTrack,
    Patient,
    RiskPrediction,
)
from app.models.enums import AnalysisStatus
from app.rules.models import (
    CandidateExamItem,
    ExamHistoryFact,
    LesionHistoryFact,
    PatientContext,
    RiskPredictionFact,
    RuleEvaluationRequest,
)
from app.schemas.plan_builder import CandidateRuleStatus
from app.services.analysis.finding_map import FindingMap, load_finding_map
from app.services.analysis.findings import Finding, derive_findings
from app.services.medical_rule_service import MedicalRuleEngineService

PROVIDER_VERSION = "local-rules-v1"
INPUT_VERSION = "confirmed-data-v1"
MISSING_WINDOW_MONTHS = 24

DISCLOSURES = (
    "本结果是待复核的工程草稿，不是诊断或医学必要性结论。",
    "疾病风险模型未接入时显示“未评估”，不产生疾病概率。",
    "发现与检查项目的关联来自工程映射，需人工复核；未经审核的规则不代表医学审核结论。",
)


def input_fingerprint(db: Session, patient: Patient, as_of_date: date) -> str:
    """决策日期之前的已确认资料指纹；用于判断结果是否过期。"""

    chunks: list[str] = []
    checks = db.scalars(
        select(HealthCheck)
        .where(HealthCheck.patient_id == patient.id, HealthCheck.check_date <= as_of_date)
        .order_by(HealthCheck.id)
    ).all()
    for check in checks:
        chunks.append(f"check:{check.id}:{check.check_date}:{check.revision_no}:{check.institution}")
        for metric in sorted(check.lab_metrics, key=lambda item: item.id):
            chunks.append(
                f"metric:{metric.id}:{metric.metric_code}:{metric.original_value}:"
                f"{metric.value}:{metric.revision_no}"
            )
        for exam in sorted(check.imaging_exams, key=lambda item: item.id):
            chunks.append(f"exam:{exam.id}:{exam.exam_date}:{exam.revision_no}")
            for lesion in sorted(exam.lesions, key=lambda item: item.id):
                chunks.append(
                    f"lesion:{lesion.id}:{lesion.lesion_type}:{lesion.location}:{lesion.size_mm}"
                )
        for history in sorted(check.exam_histories, key=lambda item: item.id):
            chunks.append(f"history:{history.id}:{history.exam_item_id}:{history.result_status}")
    for prediction in db.scalars(
        select(RiskPrediction).where(RiskPrediction.patient_id == patient.id)
    ).all():
        chunks.append(f"risk:{prediction.id}:{prediction.risk_code}:{prediction.probability}")
    return sha256("|".join(chunks).encode("utf-8")).hexdigest()[:32] if chunks else "empty-input"


def missing_information(db: Session, patient: Patient, as_of_date: date) -> list[str]:
    """明确列出无法计算的原因，不用默认值强行补全。"""

    notes: list[str] = []
    if patient.birth_date is None:
        notes.append("缺少出生日期：年龄相关规则无法判断")
    if patient.gender.value == "unknown":
        notes.append("缺少性别：性别相关规则无法判断")
    cutoff = as_of_date - timedelta(days=30 * MISSING_WINDOW_MONTHS)
    recent = db.scalar(
        select(HealthCheck)
        .where(
            HealthCheck.patient_id == patient.id,
            HealthCheck.check_date >= cutoff,
            HealthCheck.check_date <= as_of_date,
        )
        .limit(1)
    )
    if recent is None:
        notes.append(f"最近 {MISSING_WINDOW_MONTHS} 个月内没有检查记录：趋势与随访判断不可用")
    return notes


class AnalysisRunner:
    """执行一次分析并保存结果；不训练模型、不生成疾病概率。"""

    def __init__(
        self,
        db: Session,
        *,
        finding_map: FindingMap | None = None,
        rule_service: MedicalRuleEngineService | None = None,
    ) -> None:
        self.db = db
        self.finding_map = finding_map or load_finding_map()
        self.rules = rule_service or MedicalRuleEngineService(db)

    def run(
        self,
        *,
        patient: Patient,
        as_of_date: date,
        request_id: str | None = None,
        actor_account_id: str | None = None,
    ) -> AnalysisRun:
        if request_id:
            existing = self.db.scalar(
                select(AnalysisRun).where(AnalysisRun.request_id == request_id)
            )
            if existing is not None:
                if existing.patient_id != patient.id or existing.as_of_date != as_of_date:
                    raise ValueError("同一 request_id 对应不同档案或决策日期")
                return existing
        fingerprint = input_fingerprint(self.db, patient, as_of_date)
        run = AnalysisRun(
            patient_id=patient.id,
            as_of_date=as_of_date,
            status=AnalysisStatus.RUNNING,
            input_fingerprint=fingerprint,
            input_version=INPUT_VERSION,
            provider_version=PROVIDER_VERSION,
            finding_map_version=self.finding_map.version,
            request_id=request_id,
            created_by_account_id=actor_account_id,
        )
        self.db.add(run)
        self.db.flush()
        try:
            findings = derive_findings(self.db, patient, as_of_date, self.finding_map)
            candidates, notes = self._candidates(patient, as_of_date, findings, run.id)
            run.findings = [finding.to_dict() for finding in findings]
            run.candidates = candidates
            run.notes = [*DISCLOSURES, *notes, *missing_information(self.db, patient, as_of_date)]
            run.rule_set_versions = sorted(
                {
                    version
                    for candidate in candidates
                    for version in candidate["rule_set_versions"]
                }
            )
            run.summary = self._summary(findings, candidates)
            run.status = AnalysisStatus.COMPLETED
            run.is_demo = all(check.is_demo for check in patient.health_checks) and (
                len(patient.health_checks) > 0
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(run)
        return run

    # ---- 候选汇总 ---------------------------------------------------------
    def _candidates(
        self,
        patient: Patient,
        as_of_date: date,
        findings: list[Finding],
        trace_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        items = list(self.db.scalars(select(ExamItem).order_by(ExamItem.code)))
        by_code = {item.code: item for item in items}
        notes: list[str] = []

        # 发现 → 候选：同一项目来自多个发现时只保留一条，理由合并。
        sources: dict[str, list[dict[str, Any]]] = {}
        for finding in findings:
            if not finding.exam_codes:
                notes.append(f"发现 {finding.finding_code} 未登记映射，仅展示不生成候选")
                continue
            for code in finding.exam_codes:
                item = by_code.get(code)
                if item is None:
                    notes.append(
                        f"发现 {finding.finding_code} 指向的项目 {code} 不在项目目录中，未生成候选"
                    )
                    continue
                sources.setdefault(item.id, []).append(
                    {
                        "finding_code": finding.finding_code,
                        "finding_name": finding.name,
                        "system": finding.system,
                        "direction": finding.direction,
                        "reason": finding.note,
                        "evidence_refs": list(finding.evidence_refs),
                        "observed_value": finding.observed_value,
                        "reference": finding.reference,
                    }
                )

        context = self._patient_context(patient, as_of_date)
        exam_history = self._exam_history(patient, as_of_date)
        lesion_history = self._lesion_history(patient, as_of_date)
        risk_predictions = self._risk_predictions(patient)

        candidates: list[dict[str, Any]] = []
        for item in items:
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
                    # 疾病模型未接入：分数固定 0，规则路径独立成立。
                    deepfm_score=0.0,
                    risk_predictions=risk_predictions,
                    exam_history=exam_history,
                    lesion_history=lesion_history,
                    trace_id=trace_id,
                )
            )
            status = CandidateRuleStatus.from_rule_evaluation(evaluation)
            item_sources = sources.get(item.id, [])
            candidates.append(
                {
                    "exam_item_id": item.id,
                    "code": item.code,
                    "name": item.name,
                    "category": item.category,
                    "radiation": item.radiation,
                    "cost_level": item.cost_level.value,
                    "score": None,
                    "model_status": "未评估：尚无经验证的适用模型",
                    "rule_status": status.value,
                    "decision": self._decision(status),
                    "sources": item_sources,
                    "system": item_sources[0]["system"] if item_sources else item.category,
                    "missing_information": self._candidate_missing(status, item_sources),
                    "conflicts": self._conflicts(evaluation, status),
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
                    "disclosures": list(evidence_disclosures(item_sources)),
                }
            )
        duplicates = sum(max(len(candidate["sources"]) - 1, 0) for candidate in candidates)
        if duplicates:
            notes.append(f"{duplicates} 个重复建议已按检查项目合并，同一检查只计一次")
        return candidates, notes

    def _decision(self, status: CandidateRuleStatus) -> str:
        if status.forbids_selection:
            return "exclude"
        if status is CandidateRuleStatus.ALLOWED:
            return "include"
        return "require_review"

    def _candidate_missing(
        self, status: CandidateRuleStatus, sources: list[dict[str, Any]]
    ) -> list[str]:
        notes: list[str] = []
        if status is CandidateRuleStatus.NOT_CONFIGURED:
            notes.append("该项目没有已启用的适用规则，需人工确认是否纳入")
        if not sources:
            notes.append("该项目未被任何发现指向，仅作为目录基线列出")
        return notes

    def _conflicts(self, evaluation: Any, status: CandidateRuleStatus) -> list[dict[str, Any]]:
        actions = {
            decision.rule_code: decision.action.value
            for decision in evaluation.rule_decisions
        }
        conflicts: list[dict[str, Any]] = []
        if len(set(actions.values())) > 1:
            conflicts.append(
                {
                    "code": "rule_action_conflict",
                    "message": "同一项目命中多个规则且结论不同，已按最严格结论处理",
                    "rules": actions,
                }
            )
        if status is CandidateRuleStatus.NOT_CONFIGURED and evaluation.execution_trace:
            conflicts.append(
                {
                    "code": "rules_disabled",
                    "message": "适用规则全部停用，未给出自动结论",
                    "rules": actions,
                }
            )
        return conflicts

    def _summary(
        self, findings: list[Finding], candidates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        systems: dict[str, dict[str, int]] = {}
        for finding in findings:
            entry = systems.setdefault(finding.system, {"findings": 0, "candidates": 0})
            entry["findings"] += 1
        for candidate in candidates:
            for source in candidate["sources"]:
                entry = systems.setdefault(
                    source["system"], {"findings": 0, "candidates": 0}
                )
                entry["candidates"] += 1
        return {
            "finding_count": len(findings),
            "candidate_count": len(candidates),
            "include_count": sum(1 for item in candidates if item["decision"] == "include"),
            "review_count": sum(
                1 for item in candidates if item["decision"] == "require_review"
            ),
            "exclude_count": sum(1 for item in candidates if item["decision"] == "exclude"),
            "unmapped_finding_count": sum(1 for finding in findings if not finding.mapped),
            "systems": [
                {"system": system, **counts} for system, counts in sorted(systems.items())
            ],
        }

    # ---- 规则输入 ---------------------------------------------------------
    def _patient_context(self, patient: Patient, as_of_date: date) -> PatientContext:
        age = None
        if patient.birth_date:
            age = (
                as_of_date.year
                - patient.birth_date.year
                - (
                    (as_of_date.month, as_of_date.day)
                    < (patient.birth_date.month, patient.birth_date.day)
                )
            )
        return PatientContext(
            patient_id=patient.id,
            as_of_date=as_of_date,
            age=age if age is not None and 0 <= age <= 130 else None,
            sex=patient.gender.value,
        )

    def _exam_history(self, patient: Patient, as_of_date: date) -> list[ExamHistoryFact]:
        rows = self.db.execute(
            select(HealthCheck, ExamHistory)
            .join(ExamHistory, ExamHistory.health_check_id == HealthCheck.id)
            .where(HealthCheck.patient_id == patient.id, HealthCheck.check_date <= as_of_date)
        ).all()
        return [
            ExamHistoryFact(
                exam_item_id=history.exam_item_id,
                exam_code=history.exam_item.code,
                performed_at=check.check_date,
                result_status=history.result_status.value,
                radiation=history.exam_item.radiation,
                evidence_refs=[history.id],
            )
            for check, history in rows
        ]

    def _lesion_history(self, patient: Patient, as_of_date: date) -> list[LesionHistoryFact]:
        facts: list[LesionHistoryFact] = []
        for track in db_tracks(self.db, patient.id):
            observations = sorted(
                (
                    item
                    for item in track.observations
                    if item.exam_date <= as_of_date
                ),
                key=lambda item: item.exam_date,
            )
            if not observations:
                continue
            latest = observations[-1]
            growing = None
            if len(observations) >= 2 and latest.size_mm is not None:
                previous = observations[-2]
                if previous.size_mm is not None:
                    growing = latest.size_mm > previous.size_mm
            facts.append(
                LesionHistoryFact(
                    lesion_type=track.lesion_type,
                    location=track.location,
                    last_exam_date=latest.exam_date,
                    match_status=latest.match_status.value,
                    growing=growing,
                    evidence_refs=[latest.id],
                )
            )
        return facts

    def _risk_predictions(self, patient: Patient) -> list[RiskPredictionFact]:
        return [
            RiskPredictionFact(
                risk_code=item.risk_code,
                probability=item.probability,
                model_version=item.risk_model_version,
                evidence_refs=[item.id],
            )
            for item in self.db.scalars(
                select(RiskPrediction).where(RiskPrediction.patient_id == patient.id)
            ).all()
        ]


def db_tracks(db: Session, patient_id: str) -> list[LesionTrack]:
    return list(
        db.scalars(select(LesionTrack).where(LesionTrack.patient_id == patient_id)).all()
    )


def evidence_disclosures(sources: list[dict[str, Any]]) -> tuple[str, ...]:
    if not sources:
        return ("该项目没有被任何发现指向：不代表需要或不需要检查。",)
    return (
        "该项目由上述发现关联得到，需人工复核；关联不代表确诊。",
    )


def latest_observation_date(track: LesionTrack) -> date | None:
    dates = [item.exam_date for item in track.observations]
    return max(dates) if dates else None


def observation_growth(observations: list[LesionObservation]) -> bool | None:
    ordered = sorted(observations, key=lambda item: item.exam_date)
    if len(ordered) < 2:
        return None
    latest, previous = ordered[-1], ordered[-2]
    if latest.size_mm is None or previous.size_mm is None:
        return None
    return latest.size_mm > previous.size_mm
