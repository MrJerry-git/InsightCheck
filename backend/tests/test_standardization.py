import pytest

from app.features.lesion_terminology import LesionTerminology
from app.features.metric_normalizer import MetricNormalizer
from app.models import MetricDictionary
from app.models.enums import MetricStatus, NormalizationStatus
from app.schemas.domain import MetricNormalizationRequest


@pytest.fixture
def normalizer() -> MetricNormalizer:
    definition = MetricDictionary(
        metric_code="ALT",
        canonical_name="丙氨酸氨基转移酶",
        aliases=["ALT", "谷丙转氨酶", "丙氨酸氨基转移酶"],
        standard_unit="U/L",
        category="肝功能",
        unit_conversions={"IU/L": {"factor": 1.0, "offset": 0.0}},
        valid_min=0,
        valid_max=1000,
        source="TEST",
        version="test-v1",
    )
    return MetricNormalizer([definition])


@pytest.mark.parametrize("alias", ["ALT", "谷丙转氨酶", "丙氨酸氨基转移酶"])
def test_alt_aliases_map_to_one_metric(alias: str, normalizer: MetricNormalizer) -> None:
    result = normalizer.normalize(
        MetricNormalizationRequest(
            original_name=alias,
            original_value="51",
            original_unit="IU/L",
            reference_min=9,
            reference_max=50,
        )
    )

    assert result.metric_code == "ALT"
    assert result.value == 51
    assert result.standard_unit == "U/L"
    assert result.status == MetricStatus.HIGH
    assert result.normalization_status == NormalizationStatus.NORMALIZED


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        (
            MetricNormalizationRequest(
                original_name="未知指标", original_value="12", original_unit="U/L"
            ),
            NormalizationStatus.UNMAPPED_METRIC,
        ),
        (
            MetricNormalizationRequest(
                original_name="ALT", original_value="not-a-number", original_unit="U/L"
            ),
            NormalizationStatus.INVALID_VALUE,
        ),
        (
            MetricNormalizationRequest(
                original_name="ALT", original_value="12", original_unit="mg/dL"
            ),
            NormalizationStatus.UNSUPPORTED_UNIT,
        ),
        (
            MetricNormalizationRequest(
                original_name="ALT", original_value="1001", original_unit="U/L"
            ),
            NormalizationStatus.IMPLAUSIBLE_VALUE,
        ),
    ],
)
def test_normalizer_reports_non_success_states(
    payload: MetricNormalizationRequest,
    expected_status: NormalizationStatus,
    normalizer: MetricNormalizer,
) -> None:
    assert normalizer.normalize(payload).normalization_status == expected_status


@pytest.mark.parametrize("term", ["右上肺", "右肺上叶", "RUL", " rul "])
def test_lesion_location_terminology(term: str) -> None:
    result = LesionTerminology().normalize_location(term)

    assert result.matched is True
    assert result.canonical_location == "RIGHT_UPPER_LOBE"


def test_lesion_terminology_does_not_guess_unknown_location() -> None:
    result = LesionTerminology().normalize_location("未收录部位")

    assert result.matched is False
    assert result.canonical_location is None
