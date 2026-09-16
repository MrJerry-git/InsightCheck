from sqlalchemy.orm import Session

from app.features.lesion.matcher import LesionMatcher
from app.features.lesion.schemas import (
    LesionDemoAnalysisResult,
    LesionMatchDecision,
    LesionMatchingRequest,
    LesionMatchingResult,
    LesionMatchStatus,
    LesionTrackCandidate,
    LesionTrendRequest,
    LesionTrendResult,
    StructuredLesion,
    TrackPresenceStatus,
)
from app.features.lesion.trend import LesionTrendAnalyzer
from app.repositories.lesion_analysis_repository import LesionAnalysisRepository
from app.services.crud import EntityNotFoundError

DEMO_PATIENT_CODE = "DEMO-LESION-PATIENT-001"
DEMO_TRACK_CODE = "DEMO-LONGITUDINAL-LESION-001"
MEDICAL_DISCLAIMER = (
    "本系统基于历史体检数据提供健康趋势分析与体检项目辅助推荐，不构成疾病诊断、"
    "医疗处方或治疗建议，最终体检方案应由具有资质的医务人员结合实际情况确认。"
)


class LesionAnalysisService:
    """编排结构化病灶匹配和描述性变化分析，不执行影像识别。"""

    def __init__(
        self,
        matcher: LesionMatcher | None = None,
        trend_analyzer: LesionTrendAnalyzer | None = None,
    ) -> None:
        self.matcher = matcher or LesionMatcher()
        self.trend_analyzer = trend_analyzer or LesionTrendAnalyzer()

    def match(self, request: LesionMatchingRequest) -> LesionMatchingResult:
        return self.matcher.match(request)

    def analyze_trend(self, request: LesionTrendRequest) -> LesionTrendResult:
        return self.trend_analyzer.analyze(request)

    def get_demo_analysis(self, session: Session) -> LesionDemoAnalysisResult:
        repository = LesionAnalysisRepository(session)
        patient = repository.get_patient_by_code(DEMO_PATIENT_CODE)
        if patient is None:
            raise EntityNotFoundError("请先执行 python -m app.seed 创建病灶 Demo 数据")
        track = repository.get_track(patient.id, DEMO_TRACK_CODE)
        if track is None:
            raise EntityNotFoundError("病灶 Demo 轨迹不存在")

        structured = [
            StructuredLesion(
                lesion_id=observation.lesion.id,
                exam_date=observation.exam_date,
                lesion_type=observation.lesion.lesion_type,
                organ=None,
                body_part=observation.lesion.imaging_exam.body_part,
                location=observation.lesion.location,
                size_mm=observation.size_mm,
                grade=observation.grade,
            )
            for observation in sorted(track.observations, key=lambda item: item.exam_date)
        ]
        matches = self._sequential_matches(track.canonical_lesion_id, structured)
        trend = self.analyze_trend(
            LesionTrendRequest(
                track_id=track.canonical_lesion_id,
                observations=structured,
                evaluation_date=structured[-1].exam_date,
                initial_match_status=LesionMatchStatus.NEW_LESION,
                presence_status=TrackPresenceStatus.CONTINUING,
            )
        )
        return LesionDemoAnalysisResult(
            is_demo=True,
            demo_label="DEMO DATA",
            patient_code=patient.anonymous_code,
            track_id=track.canonical_lesion_id,
            canonical_location=track.location,
            matches=matches,
            trend=trend,
            disclaimer=MEDICAL_DISCLAIMER,
        )

    def _sequential_matches(
        self, track_id: str, observations: list[StructuredLesion]
    ) -> list[LesionMatchDecision]:
        decisions: list[LesionMatchDecision] = []
        history: list[StructuredLesion] = []
        for current in observations:
            previous_tracks = (
                [LesionTrackCandidate(track_id=track_id, observations=history)] if history else []
            )
            result = self.match(
                LesionMatchingRequest(
                    current_exam_date=current.exam_date,
                    previous_tracks=previous_tracks,
                    current_lesions=[current],
                    complete_body_parts=[current.body_part] if current.body_part else [],
                )
            )
            decisions.append(result.matches[0])
            if result.matches[0].status in {
                LesionMatchStatus.NEW_LESION,
                LesionMatchStatus.MATCHED,
            }:
                history.append(current)
        return decisions
