from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    HealthCheck,
    ImagingExam,
    Lesion,
    LesionObservation,
    LesionTrack,
    Patient,
)
from app.models.enums import Gender, MatchStatus


@dataclass
class LesionDemoSeedSummary:
    patient_code: str
    track_code: str
    observation_count: int
    is_demo: bool = True

    def to_dict(self) -> dict[str, str | int | bool]:
        return asdict(self)


class LesionMatchingDemoSeedService:
    """幂等创建第三阶段四年结构化病灶演示数据。"""

    PATIENT_CODE = "DEMO-LESION-PATIENT-001"
    TRACK_CODE = "DEMO-LONGITUDINAL-LESION-001"
    OBSERVATIONS = (
        (date(2023, 6, 1), 5.0, "G1"),
        (date(2024, 6, 1), 5.3, "G1"),
        (date(2025, 6, 1), 5.8, "G2"),
        (date(2026, 6, 1), 6.2, "G2"),
    )

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self) -> LesionDemoSeedSummary:
        try:
            patient = self._ensure_patient()
            lesions = [
                self._ensure_year(patient, exam_date, size_mm, grade)
                for exam_date, size_mm, grade in self.OBSERVATIONS
            ]
            track = self._ensure_track(patient)
            for (exam_date, size_mm, grade), lesion in zip(self.OBSERVATIONS, lesions, strict=True):
                self._ensure_observation(track, lesion, exam_date, size_mm, grade)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        observation_count = len(
            self.session.scalars(
                select(LesionObservation).where(LesionObservation.lesion_track_id == track.id)
            ).all()
        )
        return LesionDemoSeedSummary(
            patient_code=patient.anonymous_code,
            track_code=track.canonical_lesion_id,
            observation_count=observation_count,
        )

    def _ensure_patient(self) -> Patient:
        patient = self.session.scalar(
            select(Patient).where(Patient.anonymous_code == self.PATIENT_CODE)
        )
        if patient is None:
            patient = Patient(
                anonymous_code=self.PATIENT_CODE,
                gender=Gender.UNKNOWN,
                birth_date=None,
                height=None,
            )
            self.session.add(patient)
            self.session.flush()
        return patient

    def _ensure_year(self, patient: Patient, exam_date: date, size_mm: float, grade: str) -> Lesion:
        health_check = self.session.scalar(
            select(HealthCheck).where(
                HealthCheck.patient_id == patient.id,
                HealthCheck.check_date == exam_date,
            )
        )
        if health_check is None:
            health_check = HealthCheck(
                patient_id=patient.id,
                check_date=exam_date,
                institution="DEMO 纵向影像中心",
                is_demo=True,
            )
            self.session.add(health_check)
            self.session.flush()
        elif not health_check.is_demo:
            raise ValueError("病灶 Demo 患者存在未标记 is_demo=true 的体检批次")

        imaging_exam = self.session.scalar(
            select(ImagingExam).where(
                ImagingExam.health_check_id == health_check.id,
                ImagingExam.exam_type == "CHEST_CT",
            )
        )
        if imaging_exam is None:
            imaging_exam = ImagingExam(
                health_check_id=health_check.id,
                exam_type="CHEST_CT",
                body_part="CHEST",
                report_text="DEMO DATA：结构化病灶随访演示，不来自 CT 图片识别。",
                exam_date=exam_date,
            )
            self.session.add(imaging_exam)
            self.session.flush()

        lesion = self.session.scalar(
            select(Lesion).where(
                Lesion.imaging_exam_id == imaging_exam.id,
                Lesion.lesion_type == "DEMO_LONGITUDINAL_PULMONARY_NODULE",
            )
        )
        if lesion is None:
            lesion = Lesion(
                imaging_exam_id=imaging_exam.id,
                lesion_type="DEMO_LONGITUDINAL_PULMONARY_NODULE",
                original_location="右肺上叶",
                location="RIGHT_UPPER_LOBE",
                size_mm=size_mm,
                grade=grade,
                description="DEMO DATA：仅用于纵向匹配与变化分析演示。",
            )
            self.session.add(lesion)
            self.session.flush()
        return lesion

    def _ensure_track(self, patient: Patient) -> LesionTrack:
        track = self.session.scalar(
            select(LesionTrack).where(LesionTrack.canonical_lesion_id == self.TRACK_CODE)
        )
        if track is None:
            track = LesionTrack(
                patient_id=patient.id,
                canonical_lesion_id=self.TRACK_CODE,
                lesion_type="DEMO_LONGITUDINAL_PULMONARY_NODULE",
                location="RIGHT_UPPER_LOBE",
                first_seen=self.OBSERVATIONS[0][0],
                last_seen=self.OBSERVATIONS[-1][0],
            )
            self.session.add(track)
            self.session.flush()
        return track

    def _ensure_observation(
        self,
        track: LesionTrack,
        lesion: Lesion,
        exam_date: date,
        size_mm: float,
        grade: str,
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
                grade=grade,
                match_confidence=1.0,
                match_status=MatchStatus.MANUAL_CONFIRMED,
            )
            self.session.add(observation)
            self.session.flush()
        return observation
