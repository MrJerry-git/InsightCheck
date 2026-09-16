import json
from datetime import date
from pathlib import Path

import pytest

from app.features import FeaturePipeline, PatientFeatureRequest
from app.features.schemas import MetricObservation, MetricTrend
from app.models.enums import MetricStatus


def observation(
    year: int,
    value: float,
    *,
    reference_min: float = 3.0,
    reference_max: float = 7.0,
    status: MetricStatus = MetricStatus.NORMAL,
) -> MetricObservation:
    return MetricObservation(
        source_id=f"glu-{year}",
        metric_code="GLU",
        canonical_name="空腹血糖",
        observed_at=date(year, 1, 1),
        value=value,
        reference_min=reference_min,
        reference_max=reference_max,
        status=status,
        standard_unit="mmol/L",
        category="代谢",
    )


def build(*observations: MetricObservation):
    return FeaturePipeline().build(
        PatientFeatureRequest(
            patient_id="DEMO-FEATURE-SNAPSHOT",
            observations=list(observations),
        )
    )


@pytest.mark.parametrize(
    ("values", "expected_trend"),
    [
        ([5.1, 5.4, 5.8, 6.2], MetricTrend.RISING),
        ([6.2, 5.9, 5.5, 5.1], MetricTrend.FALLING),
        ([5.2, 5.2, 5.3, 5.2], MetricTrend.STABLE),
        ([5.1, 6.0, 5.2, 6.1], MetricTrend.FLUCTUATING),
    ],
)
def test_requested_four_year_sequences_have_expected_trend(
    values: list[float], expected_trend: MetricTrend
) -> None:
    result = build(
        *[
            observation(year, value)
            for year, value in zip(range(2023, 2027), values, strict=True)
        ]
    )

    assert result.metric_features["GLU"].trend == expected_trend


def test_three_latest_values_above_upper_are_three_consecutive_abnormal() -> None:
    result = build(
        observation(2023, 5.5, reference_max=6.0),
        observation(2024, 6.1, reference_max=6.0, status=MetricStatus.HIGH),
        observation(2025, 6.3, reference_max=6.0, status=MetricStatus.HIGH),
        observation(2026, 6.5, reference_max=6.0, status=MetricStatus.HIGH),
    )

    features = result.metric_features["GLU"]
    assert features.abnormal_count == 3
    assert features.consecutive_abnormal_count == 3


def test_normal_values_approaching_upper_boundary_raise_early_warning() -> None:
    result = build(
        observation(2023, 5.1, reference_max=6.5),
        observation(2024, 5.4, reference_max=6.5),
        observation(2025, 5.8, reference_max=6.5),
        observation(2026, 6.2, reference_max=6.5),
    )

    features = result.metric_features["GLU"]
    assert features.current_abnormal is False
    assert features.early_warning.value == "EARLY_WARNING"
    assert features.warning_reason is not None


def test_small_random_normal_fluctuation_does_not_raise_early_warning() -> None:
    result = build(
        observation(2023, 5.2, reference_max=6.5),
        observation(2024, 5.3, reference_max=6.5),
        observation(2025, 5.2, reference_max=6.5),
        observation(2026, 5.3, reference_max=6.5),
    )

    features = result.metric_features["GLU"]
    assert features.current_abnormal is False
    assert features.early_warning.value == "NONE"
    assert features.warning_reason is None


def test_single_record_reports_unknown_instead_of_fabricating_a_trend() -> None:
    result = build(observation(2026, 5.6))

    features = result.metric_features["GLU"]
    assert features.has_history is False
    assert features.trend == MetricTrend.UNKNOWN
    assert features.slope is None
    assert "不足两次" in features.trend_reason


def test_missing_calendar_year_uses_real_observation_dates_for_slope() -> None:
    result = build(
        observation(2023, 5.0, reference_max=10.0),
        observation(2025, 7.0, reference_max=10.0),
        observation(2026, 8.0, reference_max=10.0),
    )

    features = result.metric_features["GLU"]
    assert features.observation_count == 3
    assert features.source_observation_count == 3
    assert features.slope == pytest.approx(1.0, rel=0.002)


def test_zero_previous_value_returns_null_relative_change_without_crash() -> None:
    result = build(
        observation(2025, 0.0, reference_min=0.0, reference_max=10.0),
        observation(2026, 1.0, reference_min=0.0, reference_max=10.0),
    )

    features = result.metric_features["GLU"]
    assert features.previous_value == 0.0
    assert features.absolute_change == 1.0
    assert features.relative_change is None


def test_unsorted_dates_produce_same_vector_as_chronological_input() -> None:
    chronological = [
        observation(2023, 5.1),
        observation(2024, 5.4),
        observation(2025, 5.8),
        observation(2026, 6.2),
    ]
    unsorted = [chronological[3], chronological[0], chronological[2], chronological[1]]

    expected = build(*chronological)
    actual = build(*unsorted)

    assert actual == expected


def test_patient_feature_vector_matches_reviewed_json_snapshot() -> None:
    result = build(
        observation(2023, 5.1, reference_max=6.5),
        observation(2024, 5.4, reference_max=6.5),
        observation(2025, 5.8, reference_max=6.5),
        observation(2026, 6.2, reference_max=6.5),
    )
    snapshot_path = Path(__file__).with_name("snapshots") / "patient_feature_vector.json"

    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert result.model_dump(mode="json") == expected


def test_every_feature_and_the_complete_vector_are_strict_json_serializable() -> None:
    result = build(observation(2026, 5.6))

    serialized = result.model_dump(mode="json")
    strict_json = json.dumps(serialized, ensure_ascii=False, allow_nan=False)

    assert json.loads(strict_json) == serialized
    assert json.loads(result.model_dump_json()) == serialized
    assert serialized["feature_values"]["metabolic__GLU__trend_code"] is None
