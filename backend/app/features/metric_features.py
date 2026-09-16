from statistics import fmean, pstdev

from app.features.schemas import (
    EarlyWarningConfig,
    FeatureGroup,
    MetricLongitudinalFeatures,
    MetricObservation,
    TrendConfig,
)
from app.features.trend_engine import EarlyWarningEngine, TrendEngine
from app.models.enums import MetricStatus


class MetricFeatureCalculator:
    """把一个指标的多次观测转换为解释性统计与趋势特征。"""

    def __init__(
        self,
        trend_engine: TrendEngine | None = None,
        warning_engine: EarlyWarningEngine | None = None,
    ) -> None:
        self.trend_engine = trend_engine or TrendEngine()
        self.warning_engine = warning_engine or EarlyWarningEngine()

    def calculate(
        self,
        observations: list[MetricObservation],
        *,
        feature_group: FeatureGroup,
        trend_config: TrendConfig,
        warning_config: EarlyWarningConfig,
    ) -> MetricLongitudinalFeatures:
        ordered = sorted(observations, key=lambda item: item.observed_at)
        valid = [item for item in ordered if item.value is not None]
        latest_metadata = ordered[-1]
        latest_valid = valid[-1] if valid else None
        previous_valid = valid[-2] if len(valid) >= 2 else None
        values = [float(item.value) for item in valid if item.value is not None]

        absolute_change = None
        relative_change = None
        if latest_valid is not None and previous_valid is not None:
            absolute_change = float(latest_valid.value) - float(previous_valid.value)
            if float(previous_valid.value) != 0:
                relative_change = absolute_change / abs(float(previous_valid.value))

        trend = self.trend_engine.assess(ordered, trend_config)
        warning = self.warning_engine.assess(ordered, warning_config)
        current_abnormal = self._is_abnormal(latest_valid) if latest_valid else False
        current_value = float(latest_valid.value) if latest_valid else None
        reference_upper = latest_valid.reference_max if latest_valid else None
        reference_lower = latest_valid.reference_min if latest_valid else None

        return MetricLongitudinalFeatures(
            metric_code=latest_metadata.metric_code,
            canonical_name=latest_metadata.canonical_name,
            standard_unit=latest_metadata.standard_unit,
            feature_group=feature_group,
            current_value=current_value,
            previous_value=float(previous_valid.value) if previous_valid else None,
            absolute_change=absolute_change,
            relative_change=relative_change,
            mean=fmean(values) if values else None,
            std=pstdev(values) if values else None,
            min=min(values) if values else None,
            max=max(values) if values else None,
            slope=trend.slope,
            trend=trend.trend,
            current_abnormal=current_abnormal,
            abnormal_count=sum(self._is_abnormal(item) for item in valid),
            consecutive_abnormal_count=self._consecutive_abnormal_count(ordered),
            distance_to_reference_upper=(
                reference_upper - current_value
                if reference_upper is not None and current_value is not None
                else None
            ),
            distance_to_reference_lower=(
                current_value - reference_lower
                if reference_lower is not None and current_value is not None
                else None
            ),
            early_warning=warning.status,
            warning_reason=warning.reason,
            observation_count=len(valid),
            source_observation_count=len(ordered),
            missing_observation_count=len(ordered) - len(valid),
            has_history=len(valid) >= 2,
            first_to_last_relative_change=trend.first_to_last_relative_change,
            coefficient_of_variation=trend.coefficient_of_variation,
            direction_consistency=trend.direction_consistency,
            trend_reason=trend.reason,
            evidence_refs=[item.source_id for item in ordered],
        )

    @staticmethod
    def _is_abnormal(observation: MetricObservation | None) -> bool:
        if observation is None or observation.value is None:
            return False
        if observation.status in {MetricStatus.HIGH, MetricStatus.LOW}:
            return True
        if observation.reference_min is not None and observation.value < observation.reference_min:
            return True
        return bool(
            observation.reference_max is not None
            and observation.value > observation.reference_max
        )

    def _consecutive_abnormal_count(self, observations: list[MetricObservation]) -> int:
        count = 0
        for observation in reversed(observations):
            if observation.value is None or not self._is_abnormal(observation):
                break
            count += 1
        return count
