import re
import unicodedata
from collections import defaultdict

from app.features.metric_features import MetricFeatureCalculator
from app.features.schemas import (
    EarlyWarningStatus,
    FeatureGroup,
    FeaturePipelineConfig,
    FeatureValue,
    MetricLongitudinalFeatures,
    MetricObservation,
    PatientFeatureRequest,
    PatientFeatureVector,
    SystemFeatureGroup,
)


def _category_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    return re.sub(r"\s+", "", normalized)


class FeaturePipeline:
    """统一入口：从纵向指标观察生成解释对象和稳定的数值特征向量。"""

    def __init__(self, calculator: MetricFeatureCalculator | None = None) -> None:
        self.calculator = calculator or MetricFeatureCalculator()

    def build(self, request: PatientFeatureRequest) -> PatientFeatureVector:
        observations = [
            item
            for item in request.observations
            if request.as_of_date is None or item.observed_at <= request.as_of_date
        ]
        grouped: dict[str, list[MetricObservation]] = defaultdict(list)
        for observation in observations:
            grouped[observation.metric_code].append(observation)

        metric_features: dict[str, MetricLongitudinalFeatures] = {}
        for metric_code in sorted(grouped):
            metric_observations = grouped[metric_code]
            feature_group = self._resolve_group(metric_observations, request.config)
            metric_features[metric_code] = self.calculator.calculate(
                metric_observations,
                feature_group=feature_group,
                trend_config=request.config.trend,
                warning_config=request.config.early_warning,
            )

        system_groups = {
            group: self._system_group(metric_features, group) for group in FeatureGroup
        }
        feature_values = self._flatten(metric_features, system_groups, request.config)
        evidence_refs = list(
            dict.fromkeys(
                item.source_id
                for item in sorted(observations, key=lambda entry: entry.observed_at)
            )
        )
        as_of_date = request.as_of_date or (
            max((item.observed_at for item in observations), default=None)
        )
        return PatientFeatureVector(
            patient_id=request.patient_id,
            as_of_date=as_of_date,
            feature_pipeline_version=request.config.version,
            metric_features=metric_features,
            metabolic_features=system_groups[FeatureGroup.METABOLIC],
            cardiovascular_features=system_groups[FeatureGroup.CARDIOVASCULAR],
            liver_features=system_groups[FeatureGroup.LIVER],
            kidney_features=system_groups[FeatureGroup.KIDNEY],
            other_features=system_groups[FeatureGroup.OTHER],
            feature_values=feature_values,
            feature_order=list(feature_values),
            evidence_refs=evidence_refs,
        )

    @staticmethod
    def _resolve_group(
        observations: list[MetricObservation], config: FeaturePipelineConfig
    ) -> FeatureGroup:
        ordered = sorted(observations, key=lambda item: item.observed_at, reverse=True)
        for observation in ordered:
            if observation.feature_group is not None:
                return observation.feature_group

        alias_index = {
            _category_key(alias): group
            for group, aliases in config.category_aliases.items()
            for alias in aliases
        }
        for observation in ordered:
            if observation.category:
                group = alias_index.get(_category_key(observation.category))
                if group is not None:
                    return group
        return FeatureGroup.OTHER

    @staticmethod
    def _system_group(
        metric_features: dict[str, MetricLongitudinalFeatures], group: FeatureGroup
    ) -> SystemFeatureGroup:
        metrics = {
            code: features
            for code, features in metric_features.items()
            if features.feature_group == group
        }
        return SystemFeatureGroup(
            metrics=metrics,
            metric_count=len(metrics),
            currently_abnormal_metric_count=sum(
                features.current_abnormal for features in metrics.values()
            ),
            early_warning_metric_count=sum(
                features.early_warning == EarlyWarningStatus.EARLY_WARNING
                for features in metrics.values()
            ),
        )

    @staticmethod
    def _flatten(
        metric_features: dict[str, MetricLongitudinalFeatures],
        system_groups: dict[FeatureGroup, SystemFeatureGroup],
        config: FeaturePipelineConfig,
    ) -> dict[str, FeatureValue]:
        values: dict[str, FeatureValue] = {}
        for group in FeatureGroup:
            system = system_groups[group]
            values[f"{group.value}__metric_count"] = system.metric_count
            values[f"{group.value}__currently_abnormal_metric_count"] = (
                system.currently_abnormal_metric_count
            )
            values[f"{group.value}__early_warning_metric_count"] = (
                system.early_warning_metric_count
            )

        scalar_fields = (
            "current_value",
            "previous_value",
            "absolute_change",
            "relative_change",
            "mean",
            "std",
            "min",
            "max",
            "slope",
            "abnormal_count",
            "consecutive_abnormal_count",
            "distance_to_reference_upper",
            "distance_to_reference_lower",
            "observation_count",
            "source_observation_count",
            "missing_observation_count",
            "first_to_last_relative_change",
            "coefficient_of_variation",
            "direction_consistency",
        )
        for metric_code in sorted(metric_features):
            features = metric_features[metric_code]
            prefix = f"{features.feature_group.value}__{metric_code}"
            for field_name in scalar_fields:
                values[f"{prefix}__{field_name}"] = getattr(features, field_name)
            values[f"{prefix}__trend_code"] = config.trend_codes[features.trend]
            values[f"{prefix}__early_warning"] = int(
                features.early_warning == EarlyWarningStatus.EARLY_WARNING
            )
            values[f"{prefix}__current_abnormal"] = int(features.current_abnormal)
            values[f"{prefix}__has_history"] = int(features.has_history)
        return values
