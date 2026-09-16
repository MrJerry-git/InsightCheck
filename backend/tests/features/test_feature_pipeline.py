from datetime import date

import pytest

from app.features.feature_pipeline import FeaturePipeline
from app.features.schemas import (
    EarlyWarningStatus,
    FeatureGroup,
    MetricObservation,
    MetricTrend,
    PatientFeatureRequest,
)
from app.models.enums import MetricStatus


def observation(
    source_id: str,
    observed_at: date,
    value: float | None,
    *,
    metric_code: str = "ALT",
    canonical_name: str = "丙氨酸氨基转移酶",
    reference_min: float | None = 0.0,
    reference_max: float | None = 40.0,
    status: MetricStatus = MetricStatus.NORMAL,
    category: str | None = "肝功能",
    feature_group: FeatureGroup | None = None,
) -> MetricObservation:
    return MetricObservation(
        source_id=source_id,
        metric_code=metric_code,
        canonical_name=canonical_name,
        observed_at=observed_at,
        value=value,
        reference_min=reference_min,
        reference_max=reference_max,
        status=status,
        standard_unit="U/L",
        category=category,
        feature_group=feature_group,
    )


def build(*observations: MetricObservation, as_of_date: date | None = None):
    return FeaturePipeline().build(
        PatientFeatureRequest(
            patient_id="demo-patient",
            observations=list(observations),
            as_of_date=as_of_date,
        )
    )


def test_multiyear_rising_features_use_all_observations() -> None:
    result = build(
        observation("alt-2022", date(2022, 6, 1), 12.0),
        observation("alt-2023", date(2023, 6, 1), 18.0),
        observation("alt-2024", date(2024, 6, 1), 24.0),
        observation("alt-2025", date(2025, 6, 1), 30.0),
    )

    features = result.metric_features["ALT"]
    assert features.current_value == 30.0
    assert features.previous_value == 24.0
    assert features.absolute_change == 6.0
    assert features.relative_change == pytest.approx(0.25)
    assert features.mean == 21.0
    assert features.std == pytest.approx(6.7082039325)
    assert features.min == 12.0
    assert features.max == 30.0
    assert features.slope == pytest.approx(6.0, rel=0.01)
    assert features.trend == MetricTrend.RISING
    assert features.observation_count == 4
    assert features.has_history is True
    assert "回归斜率" in features.trend_reason


def test_fluctuating_history_is_not_classified_from_latest_change_only() -> None:
    result = build(
        observation("alt-2022", date(2022, 1, 1), 10.0),
        observation("alt-2023", date(2023, 1, 1), 30.0),
        observation("alt-2024", date(2024, 1, 1), 15.0),
        observation("alt-2025", date(2025, 1, 1), 25.0),
    )

    features = result.metric_features["ALT"]
    assert features.absolute_change == 10.0
    assert features.trend == MetricTrend.FLUCTUATING
    assert features.direction_consistency == pytest.approx(2 / 3)
    assert "波动" in features.trend_reason


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([35.0, 30.0, 25.0, 20.0], MetricTrend.FALLING),
        ([100.0, 101.0, 100.5, 101.0], MetricTrend.STABLE),
    ],
)
def test_falling_and_stable_trends(values: list[float], expected: MetricTrend) -> None:
    result = build(
        *[
            observation(
                f"metric-{year}",
                date(year, 1, 1),
                value,
                reference_max=200.0,
            )
            for year, value in zip(range(2022, 2026), values, strict=True)
        ]
    )

    assert result.metric_features["ALT"].trend == expected


def test_early_warning_requires_normal_continuous_approach_to_boundary() -> None:
    result = build(
        observation("alt-2022", date(2022, 6, 1), 20.0),
        observation("alt-2023", date(2023, 6, 1), 28.0),
        observation("alt-2024", date(2024, 6, 1), 34.0),
        observation("alt-2025", date(2025, 6, 1), 38.0),
    )

    features = result.metric_features["ALT"]
    assert features.current_abnormal is False
    assert features.early_warning == EarlyWarningStatus.EARLY_WARNING
    assert features.distance_to_reference_upper == 2.0
    assert features.warning_reason is not None
    assert "仍在参考区间内" in features.warning_reason
    assert "参考上限" in features.warning_reason


def test_single_record_sets_has_history_false_without_error() -> None:
    result = build(observation("alt-2025", date(2025, 1, 1), 22.0))

    features = result.metric_features["ALT"]
    assert features.has_history is False
    assert features.current_value == 22.0
    assert features.previous_value is None
    assert features.absolute_change is None
    assert features.relative_change is None
    assert features.slope is None
    assert features.std == 0.0
    assert features.trend == MetricTrend.UNKNOWN
    assert features.early_warning == EarlyWarningStatus.NONE


def test_two_records_produce_valid_directional_features() -> None:
    result = build(
        observation("alt-2024", date(2024, 1, 1), 10.0),
        observation("alt-2025", date(2025, 1, 1), 20.0),
    )

    features = result.metric_features["ALT"]
    assert features.has_history is True
    assert features.observation_count == 2
    assert features.slope == pytest.approx(10.0, rel=0.01)
    assert features.trend == MetricTrend.RISING
    assert features.early_warning == EarlyWarningStatus.NONE


def test_middle_year_and_missing_value_are_retained_as_traceable_missingness() -> None:
    result = build(
        observation("alt-2022", date(2022, 1, 1), 10.0),
        observation("alt-2023-missing", date(2023, 1, 1), None),
        observation("alt-2024", date(2024, 1, 1), 14.0),
    )

    features = result.metric_features["ALT"]
    assert features.current_value == 14.0
    assert features.previous_value == 10.0
    assert features.source_observation_count == 3
    assert features.observation_count == 2
    assert features.missing_observation_count == 1
    assert features.slope == pytest.approx(2.0, rel=0.01)
    assert features.early_warning == EarlyWarningStatus.NONE
    assert features.evidence_refs == ["alt-2022", "alt-2023-missing", "alt-2024"]


def test_all_missing_values_return_nullable_features_without_error() -> None:
    result = build(
        observation("alt-2024-missing", date(2024, 1, 1), None),
        observation("alt-2025-missing", date(2025, 1, 1), None),
    )

    features = result.metric_features["ALT"]
    assert features.current_value is None
    assert features.mean is None
    assert features.std is None
    assert features.slope is None
    assert features.observation_count == 0
    assert features.missing_observation_count == 2
    assert features.has_history is False


def test_abnormal_counts_and_reference_distances_are_explicit() -> None:
    result = build(
        observation("alt-2023", date(2023, 1, 1), 30.0),
        observation(
            "alt-2024",
            date(2024, 1, 1),
            45.0,
            status=MetricStatus.HIGH,
        ),
        observation(
            "alt-2025",
            date(2025, 1, 1),
            48.0,
            status=MetricStatus.HIGH,
        ),
    )

    features = result.metric_features["ALT"]
    assert features.current_abnormal is True
    assert features.abnormal_count == 2
    assert features.consecutive_abnormal_count == 2
    assert features.distance_to_reference_upper == -8.0
    assert features.distance_to_reference_lower == 48.0
    assert features.early_warning == EarlyWarningStatus.NONE


def test_system_groups_and_flat_vector_are_model_ready_and_deterministic() -> None:
    observations = [
        observation(
            "glu-2025",
            date(2025, 1, 1),
            5.2,
            metric_code="GLU",
            canonical_name="空腹血糖",
            reference_max=6.1,
            category="代谢",
        ),
        observation(
            "sbp-2025",
            date(2025, 1, 1),
            118.0,
            metric_code="SBP",
            canonical_name="收缩压",
            reference_max=140.0,
            category="心血管",
        ),
        observation("alt-2025", date(2025, 1, 1), 25.0),
        observation(
            "crea-2025",
            date(2025, 1, 1),
            70.0,
            metric_code="CREA",
            canonical_name="肌酐",
            reference_max=104.0,
            category=None,
            feature_group=FeatureGroup.KIDNEY,
        ),
    ]
    result = build(*reversed(observations))
    same_result = build(*observations)

    assert set(result.metabolic_features.metrics) == {"GLU"}
    assert set(result.cardiovascular_features.metrics) == {"SBP"}
    assert set(result.liver_features.metrics) == {"ALT"}
    assert set(result.kidney_features.metrics) == {"CREA"}
    assert result.feature_pipeline_version == "metric-feature-pipeline-v1.1"
    assert result.feature_order == list(result.feature_values)
    assert result.feature_order == same_result.feature_order
    assert result.feature_values == same_result.feature_values
    assert result.feature_values["metabolic__GLU__current_value"] == 5.2
    assert result.feature_values["kidney__CREA__has_history"] == 0
    assert all(
        value is None or isinstance(value, int | float | bool)
        for value in result.feature_values.values()
    )


def test_as_of_date_excludes_future_observations_and_evidence() -> None:
    result = build(
        observation("alt-2024", date(2024, 1, 1), 20.0),
        observation("alt-2025", date(2025, 1, 1), 25.0),
        as_of_date=date(2024, 12, 31),
    )

    features = result.metric_features["ALT"]
    assert features.current_value == 20.0
    assert features.has_history is False
    assert result.as_of_date == date(2024, 12, 31)
    assert result.evidence_refs == ["alt-2024"]


def test_empty_request_produces_empty_but_valid_vector() -> None:
    result = build()

    assert result.metric_features == {}
    assert result.metabolic_features.metric_count == 0
    assert result.feature_values["other__metric_count"] == 0
    assert result.as_of_date is None
    assert result.evidence_refs == []
