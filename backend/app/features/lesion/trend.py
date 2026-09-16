from datetime import date

from app.features.lesion.schemas import (
    GradeChange,
    LesionMatchStatus,
    LesionTrendPoint,
    LesionTrendRequest,
    LesionTrendResult,
    StructuredLesion,
    TrackPresenceStatus,
)
from app.features.lesion.terminology import term_key

TREND_DECIMAL_PLACES = 6
AVERAGE_DAYS_PER_MONTH = 30.4375


def calendar_months_between(earlier: date, later: date) -> float:
    whole_months = (later.year - earlier.year) * 12 + later.month - earlier.month
    day_fraction = (later.day - earlier.day) / AVERAGE_DAYS_PER_MONTH
    return max(0.0, whole_months + day_fraction)


class LesionTrendAnalyzer:
    """从已结构化且已确认归轨的观察计算描述性变化特征。"""

    def analyze(self, request: LesionTrendRequest) -> LesionTrendResult:
        observations = sorted(request.observations, key=lambda item: item.exam_date)
        first = observations[0]
        last = observations[-1]
        points = self._points(observations)
        continuous_occurrences = self._latest_continuous_occurrences(request, observations)
        absolute_change, relative_change, growth_rate = self._size_features(request, first, last)
        stable, growing, shrinking = self._direction(request, absolute_change, relative_change)
        grade_change = self._grade_change(request, first.grade, last.grade)
        months_since_last = calendar_months_between(last.exam_date, request.evaluation_date)
        new_lesion = (
            len(observations) == 1 and request.initial_match_status == LesionMatchStatus.NEW_LESION
        )
        disappeared = request.presence_status == TrackPresenceStatus.DISAPPEARED

        reasons = [f"共纳入 {len(observations)} 次结构化病灶观察"]
        if absolute_change is None:
            reasons.append("尺寸资料不足，未计算尺寸变化")
        else:
            reasons.append(f"首末尺寸绝对变化 {absolute_change:+.1f} mm")
        if growing:
            reasons.append("尺寸变化超过配置的稳定范围，趋势为增大")
        elif shrinking:
            reasons.append("尺寸变化超过配置的稳定范围，趋势为缩小")
        elif stable:
            reasons.append("尺寸变化位于配置的稳定范围内")
        if disappeared:
            reasons.append("同一检查范围未再发现该轨迹，标记为消失")
        elif request.presence_status == TrackPresenceStatus.UNRESOLVED:
            reasons.append("当前证据不足，轨迹状态未决")

        return LesionTrendResult(
            track_id=request.track_id,
            observations=points,
            absolute_size_change=absolute_change,
            relative_size_change=relative_change,
            growth_rate=growth_rate,
            grade_change=grade_change,
            continuous_occurrences=continuous_occurrences,
            months_since_last_exam=round(months_since_last, TREND_DECIMAL_PLACES),
            new_lesion=new_lesion,
            disappeared=disappeared,
            stable=stable,
            growing=growing,
            shrinking=shrinking,
            reasons=reasons,
            trend_version=request.config.version,
        )

    @staticmethod
    def _points(observations: list[StructuredLesion]) -> list[LesionTrendPoint]:
        points: list[LesionTrendPoint] = []
        previous: StructuredLesion | None = None
        for observation in observations:
            absolute_change = None
            months_from_previous = None
            if previous is not None:
                months_from_previous = calendar_months_between(
                    previous.exam_date, observation.exam_date
                )
                if previous.size_mm is not None and observation.size_mm is not None:
                    absolute_change = observation.size_mm - previous.size_mm
            points.append(
                LesionTrendPoint(
                    lesion_id=observation.lesion_id,
                    exam_date=observation.exam_date,
                    size_mm=observation.size_mm,
                    grade=observation.grade,
                    absolute_change_from_previous=(
                        round(absolute_change, TREND_DECIMAL_PLACES)
                        if absolute_change is not None
                        else None
                    ),
                    months_from_previous=(
                        round(months_from_previous, TREND_DECIMAL_PLACES)
                        if months_from_previous is not None
                        else None
                    ),
                )
            )
            previous = observation
        return points

    @staticmethod
    def _size_features(
        request: LesionTrendRequest,
        first: StructuredLesion,
        last: StructuredLesion,
    ) -> tuple[float | None, float | None, float | None]:
        if first.size_mm is None or last.size_mm is None:
            return None, None, None

        absolute_change = last.size_mm - first.size_mm
        relative_change = absolute_change / first.size_mm if first.size_mm > 0 else None
        elapsed_months = calendar_months_between(first.exam_date, last.exam_date)
        growth_rate = None
        if elapsed_months > 0:
            growth_rate = absolute_change / (elapsed_months / request.config.months_per_year)
        return (
            round(absolute_change, TREND_DECIMAL_PLACES),
            round(relative_change, TREND_DECIMAL_PLACES) if relative_change is not None else None,
            round(growth_rate, TREND_DECIMAL_PLACES) if growth_rate is not None else None,
        )

    @staticmethod
    def _direction(
        request: LesionTrendRequest,
        absolute_change: float | None,
        relative_change: float | None,
    ) -> tuple[bool, bool, bool]:
        if absolute_change is None or relative_change is None:
            return False, False, False
        stable = (
            abs(absolute_change) <= request.config.stable_absolute_change_mm
            and abs(relative_change) <= request.config.stable_relative_change
        )
        if stable:
            return True, False, False
        return False, absolute_change > 0, absolute_change < 0

    @staticmethod
    def _latest_continuous_occurrences(
        request: LesionTrendRequest, observations: list[StructuredLesion]
    ) -> int:
        count = 1
        for previous, current in zip(observations, observations[1:], strict=False):
            gap = calendar_months_between(previous.exam_date, current.exam_date)
            count = count + 1 if gap <= request.config.max_continuous_gap_months else 1
        return count

    @staticmethod
    def _grade_change(
        request: LesionTrendRequest, first_grade: str | None, last_grade: str | None
    ) -> GradeChange:
        if first_grade is None or last_grade is None:
            return GradeChange.UNKNOWN
        first_key = term_key(first_grade)
        last_key = term_key(last_grade)
        if first_key == last_key:
            return GradeChange.UNCHANGED
        first_rank = request.config.grade_order.get(first_key)
        last_rank = request.config.grade_order.get(last_key)
        if first_rank is None or last_rank is None:
            return GradeChange.CHANGED
        return GradeChange.INCREASED if last_rank > first_rank else GradeChange.DECREASED
