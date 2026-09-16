from dataclasses import dataclass

from app.features.lesion.schemas import (
    LesionMatchingConfig,
    LesionPairScore,
    LesionTrackCandidate,
    StructuredLesion,
)
from app.features.lesion.terminology import LesionTerminology, term_key

SCORE_DECIMAL_PLACES = 6


def months_between(earlier: StructuredLesion, later: StructuredLesion) -> float:
    days = (later.exam_date - earlier.exam_date).days
    return max(0.0, days / 30.4375)


@dataclass(frozen=True)
class NormalizedComparison:
    previous_type: str
    current_type: str
    previous_organ: str | None
    current_organ: str | None
    previous_body_part: str | None
    current_body_part: str | None
    previous_location: str | None
    current_location: str | None


class LesionScorer:
    """对当前病灶与既有轨迹最近观察进行可解释的确定性评分。"""

    def __init__(
        self,
        config: LesionMatchingConfig | None = None,
        terminology: LesionTerminology | None = None,
    ) -> None:
        self.config = config or LesionMatchingConfig()
        self.terminology = terminology or LesionTerminology()

    def score(self, current: StructuredLesion, track: LesionTrackCandidate) -> LesionPairScore:
        previous = max(track.observations, key=lambda item: item.exam_date)
        normalized = self._normalize(previous, current)
        reasons: list[str] = [f"基于既有轨迹 {track.track_id} 的最近一次观察"]

        type_score = float(normalized.previous_type == normalized.current_type)
        if type_score:
            reasons.append("病灶类型一致")
        else:
            reasons.append("病灶类型不一致")

        organ_score = self._organ_score(normalized)
        if organ_score:
            organ = normalized.current_organ or normalized.current_body_part
            reasons.append(f"器官/检查部位一致：{organ}")
        else:
            reasons.append("器官/检查部位缺失或不一致")

        location_score = float(
            normalized.previous_location is not None
            and normalized.previous_location == normalized.current_location
        )
        if location_score:
            reasons.append(
                f"位置均属于{self.terminology.display_location(normalized.current_location or '')}"
            )
        elif normalized.previous_location and normalized.current_location:
            reasons.append("位置不一致")
        else:
            reasons.append("位置资料不足")

        size_score = self._size_score(previous.size_mm, current.size_mm)
        if size_score >= self.config.matched_threshold:
            reasons.append(f"尺寸变化连续（{previous.size_mm:.1f} mm → {current.size_mm:.1f} mm）")
        elif previous.size_mm is None or current.size_mm is None:
            reasons.append("尺寸资料不足")
        else:
            reasons.append(
                f"尺寸连续性较低（{previous.size_mm:.1f} mm → {current.size_mm:.1f} mm）"
            )

        grade_score = float(
            previous.grade is not None
            and current.grade is not None
            and term_key(previous.grade) == term_key(current.grade)
        )
        reasons.append("分级一致" if grade_score else "分级缺失或不一致")

        component_scores = {
            "lesion_type": type_score,
            "organ": organ_score,
            "location": location_score,
            "size": size_score,
            "grade": grade_score,
        }
        weights = self.config.weights.model_dump()
        contributions = {
            name: round(score * weights[name], SCORE_DECIMAL_PLACES)
            for name, score in component_scores.items()
        }
        confidence = sum(contributions.values())

        interval_months = months_between(previous, current)
        reasons.append(f"距上次检查 {interval_months:.1f} 个月")
        if interval_months > self.config.max_supported_interval_months:
            confidence *= self.config.long_interval_multiplier
            reasons.append("检查间隔较长，置信度已下调")

        if previous.location is None or current.location is None:
            confidence = min(confidence, self.config.missing_location_confidence_cap)
            reasons.append("位置缺失，禁止自动确认匹配")
        elif normalized.previous_location != normalized.current_location:
            confidence = min(confidence, self.config.conflict_confidence_cap)
            reasons.append("位置冲突，禁止自动确认匹配")

        relative_size_change = self._relative_size_change(previous.size_mm, current.size_mm)
        if (
            relative_size_change is not None
            and relative_size_change >= self.config.extreme_size_relative_change
        ):
            confidence = min(confidence, self.config.conflict_confidence_cap)
            reasons.append("尺寸变化幅度过大，禁止自动确认匹配")

        return LesionPairScore(
            current_lesion_id=current.lesion_id,
            candidate_track_id=track.track_id,
            confidence=round(max(0.0, min(1.0, confidence)), SCORE_DECIMAL_PLACES),
            component_scores=component_scores,
            weighted_contributions=contributions,
            reasons=reasons,
        )

    def _normalize(
        self, previous: StructuredLesion, current: StructuredLesion
    ) -> NormalizedComparison:
        return NormalizedComparison(
            previous_type=self.terminology.normalize_lesion_type(previous.lesion_type),
            current_type=self.terminology.normalize_lesion_type(current.lesion_type),
            previous_organ=self.terminology.normalize_organ(previous.organ, previous.location),
            current_organ=self.terminology.normalize_organ(current.organ, current.location),
            previous_body_part=self.terminology.normalize_body_part(previous.body_part),
            current_body_part=self.terminology.normalize_body_part(current.body_part),
            previous_location=(
                self.terminology.normalize_location(previous.location).canonical_location
                if previous.location
                else None
            ),
            current_location=(
                self.terminology.normalize_location(current.location).canonical_location
                if current.location
                else None
            ),
        )

    @staticmethod
    def _organ_score(comparison: NormalizedComparison) -> float:
        if comparison.previous_organ and comparison.current_organ:
            return float(comparison.previous_organ == comparison.current_organ)
        if comparison.previous_body_part and comparison.current_body_part:
            return float(comparison.previous_body_part == comparison.current_body_part)
        return 0.0

    def _size_score(self, previous: float | None, current: float | None) -> float:
        relative_change = self._relative_size_change(previous, current)
        if relative_change is None:
            return 0.0
        return max(
            0.0,
            1.0 - relative_change / self.config.size_relative_change_for_zero_score,
        )

    @staticmethod
    def _relative_size_change(previous: float | None, current: float | None) -> float | None:
        if previous is None or current is None or previous <= 0:
            return None
        return abs(current - previous) / previous
