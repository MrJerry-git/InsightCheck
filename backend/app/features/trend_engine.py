from statistics import fmean, pstdev

from app.features.schemas import (
    EarlyWarningAssessment,
    EarlyWarningConfig,
    EarlyWarningStatus,
    MetricObservation,
    MetricTrend,
    TrendAssessment,
    TrendConfig,
)


class TrendEngine:
    """结合回归斜率、首尾变化和波动程度判断多年指标趋势。"""

    def assess(
        self, observations: list[MetricObservation], config: TrendConfig
    ) -> TrendAssessment:
        valid = [item for item in observations if item.value is not None]
        if len(valid) < 2:
            return TrendAssessment(
                trend=MetricTrend.UNKNOWN,
                slope=None,
                first_to_last_relative_change=None,
                coefficient_of_variation=0.0 if valid else None,
                direction_consistency=None,
                reason="有效观察不足两次，未推断方向性趋势",
            )

        ordered = sorted(valid, key=lambda item: item.observed_at)
        values = [float(item.value) for item in ordered if item.value is not None]
        elapsed_years = [
            (item.observed_at - ordered[0].observed_at).days / config.days_per_year
            for item in ordered
        ]
        slope = self._linear_slope(elapsed_years, values, config.numeric_epsilon)
        first_last_relative = self._relative_change(
            values[0], values[-1], config.numeric_epsilon
        )
        mean_value = fmean(values)
        std_value = pstdev(values)
        coefficient_of_variation = std_value / max(abs(mean_value), config.numeric_epsilon)
        direction_consistency = self._direction_consistency(
            values, slope, config.numeric_epsilon
        )
        trend, reason = self._classify(
            slope=slope,
            mean_value=mean_value,
            first_last_relative=first_last_relative,
            coefficient_of_variation=coefficient_of_variation,
            direction_consistency=direction_consistency,
            observation_count=len(values),
            config=config,
        )
        return TrendAssessment(
            trend=trend,
            slope=slope,
            first_to_last_relative_change=first_last_relative,
            coefficient_of_variation=coefficient_of_variation,
            direction_consistency=direction_consistency,
            reason=reason,
        )

    @staticmethod
    def _linear_slope(x_values: list[float], y_values: list[float], epsilon: float) -> float | None:
        x_mean = fmean(x_values)
        y_mean = fmean(y_values)
        denominator = sum((value - x_mean) ** 2 for value in x_values)
        if denominator <= epsilon:
            return None
        numerator = sum(
            (x_value - x_mean) * (y_value - y_mean)
            for x_value, y_value in zip(x_values, y_values, strict=True)
        )
        return numerator / denominator

    @staticmethod
    def _relative_change(first: float, last: float, epsilon: float) -> float | None:
        if abs(first) <= epsilon:
            return None
        return (last - first) / abs(first)

    @staticmethod
    def _direction_consistency(
        values: list[float], slope: float | None, epsilon: float
    ) -> float | None:
        changes = [
            current - previous
            for previous, current in zip(values, values[1:], strict=False)
            if abs(current - previous) > epsilon
        ]
        if not changes:
            return 1.0
        if slope is None or abs(slope) <= epsilon:
            positive = sum(change > 0 for change in changes)
            negative = sum(change < 0 for change in changes)
            return max(positive, negative) / len(changes)
        matches = sum((change > 0) == (slope > 0) for change in changes)
        return matches / len(changes)

    @staticmethod
    def _classify(
        *,
        slope: float | None,
        mean_value: float,
        first_last_relative: float | None,
        coefficient_of_variation: float,
        direction_consistency: float | None,
        observation_count: int,
        config: TrendConfig,
    ) -> tuple[MetricTrend, str]:
        normalized_slope = (
            slope / max(abs(mean_value), config.numeric_epsilon) if slope is not None else 0.0
        )
        relative_change = first_last_relative or 0.0
        consistency = direction_consistency if direction_consistency is not None else 0.0

        volatile = (
            observation_count >= 3
            and coefficient_of_variation >= config.fluctuation_cv_threshold
            and consistency < config.direction_consistency_threshold
        )
        if volatile:
            return MetricTrend.FLUCTUATING, "波动系数较高且相邻变化方向不一致"

        rising = (
            normalized_slope > config.stable_normalized_slope_threshold
            and relative_change > config.stable_first_last_relative_threshold
            and consistency >= config.direction_consistency_threshold
        )
        if rising:
            return MetricTrend.RISING, "回归斜率、首尾变化率与相邻变化方向共同支持上升"

        falling = (
            normalized_slope < -config.stable_normalized_slope_threshold
            and relative_change < -config.stable_first_last_relative_threshold
            and consistency >= config.direction_consistency_threshold
        )
        if falling:
            return MetricTrend.FALLING, "回归斜率、首尾变化率与相邻变化方向共同支持下降"

        stable_magnitude = (
            abs(normalized_slope) <= config.stable_normalized_slope_threshold
            and abs(relative_change) <= config.stable_first_last_relative_threshold
            and coefficient_of_variation < config.fluctuation_cv_threshold
        )
        if stable_magnitude:
            return MetricTrend.STABLE, "回归斜率、首尾变化率和总体波动均在稳定阈值内"

        mixed_direction = (
            observation_count >= 3
            and consistency < config.direction_consistency_threshold
        )
        if mixed_direction and coefficient_of_variation > config.numeric_epsilon:
            return MetricTrend.FLUCTUATING, "多年相邻变化方向反复，未形成一致上升或下降"

        return MetricTrend.STABLE, "回归斜率或首尾变化未同时超过稳定阈值"


class EarlyWarningEngine:
    """识别仍在参考区间内、连续接近同一参考界限的指标。"""

    def assess(
        self, observations: list[MetricObservation], config: EarlyWarningConfig
    ) -> EarlyWarningAssessment:
        valid = sorted(
            (item for item in observations if item.value is not None),
            key=lambda item: item.observed_at,
        )
        if len(valid) < config.minimum_observations:
            return EarlyWarningAssessment(status=EarlyWarningStatus.NONE, reason=None)

        streak = self._latest_directional_streak(valid, config)
        if len(streak) < config.minimum_observations:
            return EarlyWarningAssessment(status=EarlyWarningStatus.NONE, reason=None)

        current = streak[-1]
        if current.reference_min is None or current.reference_max is None:
            return EarlyWarningAssessment(status=EarlyWarningStatus.NONE, reason=None)
        if current.reference_max <= current.reference_min:
            return EarlyWarningAssessment(status=EarlyWarningStatus.NONE, reason=None)
        if not current.reference_min <= float(current.value) <= current.reference_max:
            return EarlyWarningAssessment(status=EarlyWarningStatus.NONE, reason=None)

        rising = float(streak[-1].value) > float(streak[-2].value)
        boundary_distances = self._boundary_distances(streak, rising)
        if boundary_distances is None:
            return EarlyWarningAssessment(status=EarlyWarningStatus.NONE, reason=None)
        if not all(
            later < earlier
            for earlier, later in zip(boundary_distances, boundary_distances[1:], strict=False)
        ):
            return EarlyWarningAssessment(status=EarlyWarningStatus.NONE, reason=None)

        reference_width = current.reference_max - current.reference_min
        current_fraction = boundary_distances[-1] / reference_width
        if current_fraction > config.boundary_distance_fraction:
            return EarlyWarningAssessment(status=EarlyWarningStatus.NONE, reason=None)

        direction = "上升并接近参考上限" if rising else "下降并接近参考下限"
        boundary = "上限" if rising else "下限"
        reason = (
            f"连续 {len(streak)} 次同方向变化，指标仍在参考区间内，"
            f"距参考{boundary} {boundary_distances[-1]:.3g}，呈{direction}趋势"
        )
        return EarlyWarningAssessment(status=EarlyWarningStatus.EARLY_WARNING, reason=reason)

    @staticmethod
    def _latest_directional_streak(
        observations: list[MetricObservation], config: EarlyWarningConfig
    ) -> list[MetricObservation]:
        if len(observations) < 2:
            return observations
        latest_change = float(observations[-1].value) - float(observations[-2].value)
        if abs(latest_change) <= config.direction_epsilon:
            return [observations[-1]]
        direction = 1 if latest_change > 0 else -1
        streak = [observations[-1]]
        current = observations[-1]
        for previous in reversed(observations[:-1]):
            gap_months = (current.observed_at - previous.observed_at).days / (
                config.average_days_per_month
            )
            change = float(current.value) - float(previous.value)
            if gap_months > config.max_gap_months:
                break
            if abs(change) <= config.direction_epsilon or (change > 0) != (direction > 0):
                break
            streak.append(previous)
            current = previous
        return list(reversed(streak))

    @staticmethod
    def _boundary_distances(
        observations: list[MetricObservation], rising: bool
    ) -> list[float] | None:
        distances: list[float] = []
        for item in observations:
            if item.reference_min is None or item.reference_max is None:
                return None
            value = float(item.value)
            if not item.reference_min <= value <= item.reference_max:
                return None
            distance = item.reference_max - value if rising else value - item.reference_min
            distances.append(distance)
        return distances
