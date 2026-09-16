from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Lesion, LesionObservation, LesionTrack, Patient


class LesionAnalysisRepository:
    """为纵向病灶分析读取结构化观察，不在此层计算匹配。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_patient_by_code(self, anonymous_code: str) -> Patient | None:
        return self.session.scalar(select(Patient).where(Patient.anonymous_code == anonymous_code))

    def get_track(self, patient_id: str, canonical_lesion_id: str) -> LesionTrack | None:
        observations = (
            selectinload(LesionTrack.observations)
            .selectinload(LesionObservation.lesion)
            .selectinload(Lesion.imaging_exam)
        )
        return self.session.scalar(
            select(LesionTrack)
            .options(observations)
            .where(
                LesionTrack.patient_id == patient_id,
                LesionTrack.canonical_lesion_id == canonical_lesion_id,
            )
        )
