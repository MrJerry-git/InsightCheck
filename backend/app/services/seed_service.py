from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.lesion_terminology import LesionTerminology
from app.features.metric_normalizer import MetricNormalizer
from app.models import (
    ExamHistory,
    ExamItem,
    HealthCheck,
    ImagingExam,
    LabMetric,
    Lesion,
    LesionObservation,
    LesionTrack,
    MetricDictionary,
    Patient,
)
from app.models.enums import CostLevel, ExamResultStatus, Gender, MatchStatus
from app.schemas.domain import MetricNormalizationRequest


@dataclass
class SeedSummary:
    patient_code: str
    health_check_count: int
    lab_metric_count: int
    imaging_exam_count: int
    lesion_observation_count: int
    is_demo: bool = True

    def to_dict(self) -> dict[str, str | int | bool]:
        return asdict(self)


class DemoSeedService:
    """幂等创建显式标记的合成演示数据，不产生模型或推荐结果。"""

    PATIENT_CODE = "DEMO-PATIENT-001"
    TRACK_CODE = "DEMO-LESION-TRACK-001"
    YEARS = (
        (date(2022, 6, 18), "ALT", "22", "右上肺", 4.0),
        (date(2023, 6, 20), "谷丙转氨酶", "28", "右肺上叶", 4.2),
        (date(2024, 6, 16), "丙氨酸氨基转移酶", "35", "RUL", 4.4),
        (date(2025, 6, 22), "ALT", "42", "右肺上叶", 4.6),
    )

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self) -> SeedSummary:
        try:
            dictionary = self._ensure_metric_dictionary()
            chest_ct = self._ensure_exam_item(
                code="CHEST_CT",
                name="胸部 CT（DEMO 项目字典）",
                category="影像检查",
                description="DEMO DATA：仅用于工程数据关系演示，不代表推荐。",
                radiation=True,
                cost_level=CostLevel.HIGH,
            )
            self._ensure_exam_item(
                code="LIVER_FUNCTION_PANEL",
                name="肝功能组合（DEMO 项目字典）",
                category="实验室检查",
                description="DEMO DATA：仅用于工程数据关系演示，不代表推荐。",
                radiation=False,
                cost_level=CostLevel.LOW,
            )
            patient = self._ensure_patient()
            normalizer = MetricNormalizer([dictionary])
            terminology = LesionTerminology()
            lesions: list[tuple[Lesion, date, float]] = []

            for check_date, metric_name, metric_value, location, lesion_size in self.YEARS:
                health_check = self._ensure_health_check(patient, check_date)
                self._ensure_lab_metric(
                    health_check, normalizer, metric_name=metric_name, metric_value=metric_value
                )
                imaging_exam = self._ensure_imaging_exam(health_check, check_date)
                lesion = self._ensure_lesion(
                    imaging_exam,
                    location=location,
                    canonical_location=terminology.normalize_location(location).canonical_location,
                    size_mm=lesion_size,
                )
                lesions.append((lesion, check_date, lesion_size))
                self._ensure_exam_history(health_check, chest_ct)

            track = self._ensure_lesion_track(patient)
            for lesion, exam_date, lesion_size in lesions:
                self._ensure_observation(track, lesion, exam_date, lesion_size)

            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return SeedSummary(
            patient_code=patient.anonymous_code,
            health_check_count=self._count(HealthCheck, patient_id=patient.id),
            lab_metric_count=self._count_for_checks(LabMetric, patient.id),
            imaging_exam_count=self._count_for_checks(ImagingExam, patient.id),
            lesion_observation_count=self._count(LesionObservation, lesion_track_id=track.id),
        )

    def _ensure_metric_dictionary(self) -> MetricDictionary:
        definition = self.session.scalar(
            select(MetricDictionary).where(MetricDictionary.metric_code == "ALT")
        )
        if definition is None:
            definition = MetricDictionary(
                metric_code="ALT",
                canonical_name="丙氨酸氨基转移酶",
                aliases=["ALT", "谷丙转氨酶", "丙氨酸氨基转移酶"],
                standard_unit="U/L",
                category="肝功能",
                unit_conversions={
                    "U/L": {"factor": 1.0, "offset": 0.0},
                    "IU/L": {"factor": 1.0, "offset": 0.0},
                },
                valid_min=0,
                valid_max=1000,
                source="PROJECT_DEMO_DICTIONARY",
                version="demo-v1",
            )
            self.session.add(definition)
            self.session.flush()
        return definition

    def _ensure_exam_item(
        self,
        *,
        code: str,
        name: str,
        category: str,
        description: str,
        radiation: bool,
        cost_level: CostLevel,
    ) -> ExamItem:
        item = self.session.scalar(select(ExamItem).where(ExamItem.code == code))
        if item is None:
            item = ExamItem(
                code=code,
                name=name,
                category=category,
                description=description,
                radiation=radiation,
                cost_level=cost_level,
                recommended_interval_months=None,
            )
            self.session.add(item)
            self.session.flush()
        return item

    def _ensure_patient(self) -> Patient:
        patient = self.session.scalar(
            select(Patient).where(Patient.anonymous_code == self.PATIENT_CODE)
        )
        if patient is None:
            patient = Patient(
                anonymous_code=self.PATIENT_CODE,
                gender=Gender.UNKNOWN,
                birth_date=date(2002, 3, 15),
                height=170.0,
            )
            self.session.add(patient)
            self.session.flush()
        return patient

    def _ensure_health_check(self, patient: Patient, check_date: date) -> HealthCheck:
        health_check = self.session.scalar(
            select(HealthCheck).where(
                HealthCheck.patient_id == patient.id,
                HealthCheck.check_date == check_date,
            )
        )
        if health_check is None:
            health_check = HealthCheck(
                patient_id=patient.id,
                check_date=check_date,
                institution="DEMO 健康中心",
                is_demo=True,
            )
            self.session.add(health_check)
            self.session.flush()
        elif not health_check.is_demo:
            raise ValueError("演示患者下存在未标记 is_demo=true 的同日体检记录")
        return health_check

    def _ensure_lab_metric(
        self,
        health_check: HealthCheck,
        normalizer: MetricNormalizer,
        *,
        metric_name: str,
        metric_value: str,
    ) -> LabMetric:
        metric = self.session.scalar(
            select(LabMetric).where(
                LabMetric.health_check_id == health_check.id,
                LabMetric.metric_code == "ALT",
            )
        )
        if metric is None:
            result = normalizer.normalize(
                MetricNormalizationRequest(
                    original_name=metric_name,
                    original_value=metric_value,
                    original_unit="U/L",
                    reference_min=9,
                    reference_max=50,
                )
            )
            metric = LabMetric(
                health_check_id=health_check.id,
                metric_code=result.metric_code,
                canonical_name=result.canonical_name,
                original_name=result.original_name,
                original_value=result.original_value,
                value=result.value,
                original_unit=result.original_unit,
                standard_unit=result.standard_unit,
                reference_min=result.reference_min,
                reference_max=result.reference_max,
                status=result.status,
                normalization_status=result.normalization_status,
                normalization_version=result.normalization_version,
            )
            self.session.add(metric)
            self.session.flush()
        return metric

    def _ensure_imaging_exam(self, health_check: HealthCheck, exam_date: date) -> ImagingExam:
        exam = self.session.scalar(
            select(ImagingExam).where(
                ImagingExam.health_check_id == health_check.id,
                ImagingExam.exam_type == "CHEST_CT",
            )
        )
        if exam is None:
            exam = ImagingExam(
                health_check_id=health_check.id,
                exam_type="CHEST_CT",
                body_part="CHEST",
                report_text="DEMO DATA：合成影像文字，仅用于工程链路测试。",
                exam_date=exam_date,
            )
            self.session.add(exam)
            self.session.flush()
        return exam

    def _ensure_lesion(
        self,
        imaging_exam: ImagingExam,
        *,
        location: str,
        canonical_location: str | None,
        size_mm: float,
    ) -> Lesion:
        if canonical_location is None:
            raise ValueError(f"演示病灶位置术语未映射: {location}")
        lesion = self.session.scalar(
            select(Lesion).where(
                Lesion.imaging_exam_id == imaging_exam.id,
                Lesion.lesion_type == "DEMO_PULMONARY_NODULE",
            )
        )
        if lesion is None:
            lesion = Lesion(
                imaging_exam_id=imaging_exam.id,
                lesion_type="DEMO_PULMONARY_NODULE",
                original_location=location,
                location=canonical_location,
                size_mm=size_mm,
                grade=None,
                description="DEMO DATA：合成病灶观察，不构成医学结论。",
            )
            self.session.add(lesion)
            self.session.flush()
        return lesion

    def _ensure_exam_history(self, health_check: HealthCheck, item: ExamItem) -> ExamHistory:
        history = self.session.scalar(
            select(ExamHistory).where(
                ExamHistory.health_check_id == health_check.id,
                ExamHistory.exam_item_id == item.id,
            )
        )
        if history is None:
            history = ExamHistory(
                health_check_id=health_check.id,
                exam_item_id=item.id,
                result_status=ExamResultStatus.COMPLETED,
            )
            self.session.add(history)
            self.session.flush()
        return history

    def _ensure_lesion_track(self, patient: Patient) -> LesionTrack:
        track = self.session.scalar(
            select(LesionTrack).where(LesionTrack.canonical_lesion_id == self.TRACK_CODE)
        )
        if track is None:
            track = LesionTrack(
                patient_id=patient.id,
                canonical_lesion_id=self.TRACK_CODE,
                lesion_type="DEMO_PULMONARY_NODULE",
                location="RIGHT_UPPER_LOBE",
                first_seen=self.YEARS[0][0],
                last_seen=self.YEARS[-1][0],
            )
            self.session.add(track)
            self.session.flush()
        return track

    def _ensure_observation(
        self, track: LesionTrack, lesion: Lesion, exam_date: date, size_mm: float
    ) -> LesionObservation:
        observation = self.session.scalar(
            select(LesionObservation).where(LesionObservation.lesion_id == lesion.id)
        )
        if observation is None:
            observation = LesionObservation(
                lesion_track_id=track.id,
                lesion_id=lesion.id,
                exam_date=exam_date,
                size_mm=size_mm,
                grade=None,
                match_confidence=1.0,
                match_status=MatchStatus.MANUAL_CONFIRMED,
            )
            self.session.add(observation)
            self.session.flush()
        return observation

    def _count(self, model: type, **criteria: object) -> int:
        return len(self.session.scalars(select(model).filter_by(**criteria)).all())

    def _count_for_checks(self, model: type, patient_id: str) -> int:
        statement = (
            select(model)
            .join(HealthCheck, model.health_check_id == HealthCheck.id)
            .where(HealthCheck.patient_id == patient_id)
        )
        return len(self.session.scalars(statement).all())
