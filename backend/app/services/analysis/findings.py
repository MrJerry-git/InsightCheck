"""把已确认资料整理成"发现"（T04/T05 的输入）。

发现来自服务端确定性判断：指标超出参考区间或带异常标记、影像报告中的可追踪病灶。
发现不是诊断，也不产生疾病概率；未命中映射的发现进入待映射队列。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HealthCheck, LabMetric, MetricDictionary, Patient
from app.models.enums import MetricStatus
from app.services.analysis.finding_map import FindingMap


@dataclass(frozen=True)
class Finding:
    finding_code: str
    name: str
    system: str
    severity: str
    direction: str
    observed_value: str | None
    reference: str | None
    evidence_refs: tuple[str, ...]
    mapped: bool
    exam_codes: tuple[str, ...]
    note: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["evidence_refs"] = list(self.evidence_refs)
        payload["exam_codes"] = list(self.exam_codes)
        return payload


def direction_of(metric: LabMetric) -> str | None:
    """异常方向：优先使用已确认的状态标记，否则与参考区间比较。"""

    if metric.status is MetricStatus.HIGH:
        return "high"
    if metric.status is MetricStatus.LOW:
        return "low"
    if metric.value is None:
        return None
    if metric.reference_max is not None and metric.value > metric.reference_max:
        return "high"
    if metric.reference_min is not None and metric.value < metric.reference_min:
        return "low"
    return None


def format_reference(metric: LabMetric) -> str | None:
    if metric.reference_min is None and metric.reference_max is None:
        return None
    low = "-∞" if metric.reference_min is None else f"{metric.reference_min:g}"
    high = "+∞" if metric.reference_max is None else f"{metric.reference_max:g}"
    unit = metric.standard_unit or metric.original_unit or ""
    return f"{low} ~ {high} {unit}".strip()


def confirmed_metrics(
    db: Session, patient: Patient, as_of_date: date
) -> dict[str, list[tuple[HealthCheck, LabMetric]]]:
    """按指标编码收集决策日期之前的记录，按日期升序。"""

    rows = db.execute(
        select(HealthCheck, LabMetric)
        .join(LabMetric, LabMetric.health_check_id == HealthCheck.id)
        .where(HealthCheck.patient_id == patient.id, HealthCheck.check_date <= as_of_date)
        .order_by(HealthCheck.check_date, LabMetric.id)
    ).all()
    grouped: dict[str, list[tuple[HealthCheck, LabMetric]]] = {}
    for check, metric in rows:
        grouped.setdefault(metric.metric_code, []).append((check, metric))
    return grouped


def derive_findings(
    db: Session,
    patient: Patient,
    as_of_date: date,
    finding_map: FindingMap,
) -> list[Finding]:
    findings: list[Finding] = []
    categories = {
        item.metric_code: item.category
        for item in db.scalars(select(MetricDictionary)).all()
    }
    for metric_code, records in sorted(confirmed_metrics(db, patient, as_of_date).items()):
        latest_check, latest = records[-1]
        direction = direction_of(latest)
        if direction is None:
            continue
        abnormal_evidence = tuple(
            metric.id for _, metric in records if direction_of(metric) is not None
        )
        rules = tuple(
            rule
            for rule in finding_map.for_metric(metric_code)
            if not rule.directions or direction in rule.directions
        )
        if not rules:
            findings.append(
                Finding(
                    finding_code=f"{metric_code}_{direction.upper()}",
                    name=f"{latest.canonical_name}异常",
                    system=categories.get(metric_code, "未分类"),
                    severity="unknown",
                    direction=direction,
                    observed_value=latest.original_value,
                    reference=format_reference(latest),
                    evidence_refs=abnormal_evidence,
                    mapped=False,
                    exam_codes=(),
                    note="该发现尚未登记到检查—发现映射，保留展示并进入待映射队列",
                )
            )
            continue
        for rule in rules:
            findings.append(
                Finding(
                    finding_code=rule.finding_code,
                    name=rule.name,
                    system=rule.system,
                    severity=rule.severity,
                    direction=direction,
                    observed_value=latest.original_value,
                    reference=format_reference(latest),
                    evidence_refs=abnormal_evidence,
                    mapped=True,
                    exam_codes=rule.exam_codes,
                    note=rule.note,
                )
            )
    findings.extend(_lesion_findings(db, patient, as_of_date, finding_map))
    return findings


def _lesion_findings(
    db: Session, patient: Patient, as_of_date: date, finding_map: FindingMap
) -> list[Finding]:
    from app.models import ImagingExam, Lesion

    rows = db.execute(
        select(ImagingExam, Lesion)
        .join(Lesion, Lesion.imaging_exam_id == ImagingExam.id)
        .join(HealthCheck, ImagingExam.health_check_id == HealthCheck.id)
        .where(HealthCheck.patient_id == patient.id, ImagingExam.exam_date <= as_of_date)
        .order_by(ImagingExam.exam_date)
    ).all()
    grouped: dict[str, list[tuple[ImagingExam, Lesion]]] = {}
    for exam, lesion in rows:
        text = f"{lesion.lesion_type} {lesion.original_location} {lesion.location}"
        for rule in finding_map.for_lesion(text):
            grouped.setdefault(rule.finding_code, []).append((exam, lesion))
    findings: list[Finding] = []
    for finding_code, items in sorted(grouped.items()):
        rule = finding_map.rule(finding_code)
        if rule is None:
            continue
        exam, lesion = items[-1]
        size = f"{lesion.size_mm:g} mm" if lesion.size_mm is not None else "大小未记录"
        findings.append(
            Finding(
                finding_code=rule.finding_code,
                name=rule.name,
                system=rule.system,
                severity=rule.severity,
                direction="observation",
                observed_value=f"{lesion.location} {size}（{exam.exam_date}）",
                reference=None,
                evidence_refs=tuple(lesion_item.id for _, lesion_item in items),
                mapped=True,
                exam_codes=rule.exam_codes,
                note=rule.note,
            )
        )
    return findings
