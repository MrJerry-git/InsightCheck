import math
import re
import unicodedata
from collections.abc import Iterable

from app.models.domain import MetricDictionary
from app.models.enums import MetricStatus, NormalizationStatus
from app.schemas.domain import MetricNormalizationRequest, MetricNormalizationResult

NORMALIZATION_VERSION = "metric-normalizer-v1"


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    return re.sub(r"\s+", "", normalized)


def _parse_finite_number(value: str) -> float | None:
    try:
        parsed = float(value.strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


class MetricNormalizer:
    """使用版本化指标字典完成确定性的名称、单位与基础值校验。"""

    def __init__(self, dictionaries: Iterable[MetricDictionary]) -> None:
        self._alias_index: dict[str, MetricDictionary] = {}
        for definition in dictionaries:
            names = {definition.metric_code, definition.canonical_name, *definition.aliases}
            for name in names:
                self._alias_index[_normalize_text(name)] = definition

    def normalize(self, request: MetricNormalizationRequest) -> MetricNormalizationResult:
        definition = self._alias_index.get(_normalize_text(request.original_name))
        if definition is None:
            return self._result(
                request,
                normalization_status=NormalizationStatus.UNMAPPED_METRIC,
                issues=["指标名称未匹配到当前版本的指标字典"],
            )

        numeric_value = _parse_finite_number(request.original_value)
        if numeric_value is None:
            return self._result(
                request,
                definition=definition,
                normalization_status=NormalizationStatus.INVALID_VALUE,
                issues=["原始值不是有限数值"],
            )

        conversion = self._resolve_conversion(definition, request.original_unit)
        if conversion is None:
            return self._result(
                request,
                definition=definition,
                normalization_status=NormalizationStatus.UNSUPPORTED_UNIT,
                issues=["原始单位无法转换为字典规定的标准单位"],
            )

        factor, offset = conversion
        value = numeric_value * factor + offset
        reference_min = (
            request.reference_min * factor + offset if request.reference_min is not None else None
        )
        reference_max = (
            request.reference_max * factor + offset if request.reference_max is not None else None
        )

        if reference_min is not None and reference_max is not None:
            if reference_min > reference_max:
                return self._result(
                    request,
                    definition=definition,
                    value=value,
                    reference_min=reference_min,
                    reference_max=reference_max,
                    normalization_status=NormalizationStatus.INVALID_REFERENCE,
                    issues=["参考范围下限大于上限"],
                )

        if definition.valid_min is not None and value < definition.valid_min:
            return self._result(
                request,
                definition=definition,
                value=value,
                reference_min=reference_min,
                reference_max=reference_max,
                normalization_status=NormalizationStatus.IMPLAUSIBLE_VALUE,
                issues=["标准化结果低于字典的基础有效值边界"],
            )
        if definition.valid_max is not None and value > definition.valid_max:
            return self._result(
                request,
                definition=definition,
                value=value,
                reference_min=reference_min,
                reference_max=reference_max,
                normalization_status=NormalizationStatus.IMPLAUSIBLE_VALUE,
                issues=["标准化结果高于字典的基础有效值边界"],
            )

        status = MetricStatus.UNKNOWN
        if reference_min is not None and value < reference_min:
            status = MetricStatus.LOW
        elif reference_max is not None and value > reference_max:
            status = MetricStatus.HIGH
        elif reference_min is not None or reference_max is not None:
            status = MetricStatus.NORMAL

        return self._result(
            request,
            definition=definition,
            value=value,
            reference_min=reference_min,
            reference_max=reference_max,
            status=status,
            normalization_status=NormalizationStatus.NORMALIZED,
        )

    @staticmethod
    def _resolve_conversion(
        definition: MetricDictionary, original_unit: str | None
    ) -> tuple[float, float] | None:
        if definition.standard_unit is None:
            return (1.0, 0.0) if original_unit is None else None
        if original_unit is None:
            return None

        unit_key = _normalize_text(original_unit)
        if unit_key == _normalize_text(definition.standard_unit):
            return 1.0, 0.0
        for configured_unit, conversion in definition.unit_conversions.items():
            if _normalize_text(configured_unit) == unit_key:
                return float(conversion.get("factor", 1.0)), float(conversion.get("offset", 0.0))
        return None

    @staticmethod
    def _result(
        request: MetricNormalizationRequest,
        *,
        definition: MetricDictionary | None = None,
        value: float | None = None,
        reference_min: float | None = None,
        reference_max: float | None = None,
        status: MetricStatus = MetricStatus.UNKNOWN,
        normalization_status: NormalizationStatus,
        issues: list[str] | None = None,
    ) -> MetricNormalizationResult:
        return MetricNormalizationResult(
            metric_code=definition.metric_code if definition else None,
            canonical_name=definition.canonical_name if definition else None,
            original_name=request.original_name,
            original_value=request.original_value,
            value=value,
            original_unit=request.original_unit,
            standard_unit=definition.standard_unit if definition else None,
            reference_min=reference_min,
            reference_max=reference_max,
            status=status,
            normalization_status=normalization_status,
            normalization_version=NORMALIZATION_VERSION,
            issues=issues or [],
        )
