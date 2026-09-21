"""跨系统汇总的编排逻辑。"""

from __future__ import annotations

from datetime import date

from app.cross_system.schemas import (
    AbnormalityItem,
    CrossSystemSummary,
    NumericMetricSummary,
    Observation,
    QualitativeMetricSummary,
    QualitativeTimelineEntry,
    SystemGroup,
    TextMetricSummary,
    TextTimelineEntry,
    TimelinePoint,
)
from app.features.schemas import MetricObservation, MetricStatus, MetricTrend, TrendConfig
from app.features.trend_engine import TrendEngine


class CrossSystemSummarizer:
    """H05 跨系统趋势及异常整理服务。"""

    VERSION = "cross-system-summary-v1"

    def __init__(self, trend_engine: TrendEngine | None = None) -> None:
        self._trend_engine = trend_engine or TrendEngine()
        self._trend_config = TrendConfig()

    def summarize(
        self, observations: list[Observation], as_of: date | None = None
    ) -> CrossSystemSummary:
        decision_date = as_of or date.today()
        notes: list[str] = []

        usable, future = self._split_future(observations, decision_date)
        if future:
            notes.append(
                f"已排除 {len(future)} 条决策日期 {decision_date.isoformat()}"
                " 之后的记录，不参与汇总"
            )

        groups: dict[tuple[str, str], SystemGroup] = {}
        abnormalities: list[AbnormalityItem] = []

        for key in sorted({(o.category, o.system) for o in usable}):
            groups[key] = SystemGroup(category=key[0], system=key[1])

        by_metric: dict[str, list[Observation]] = {}
        for obs in usable:
            by_metric.setdefault(obs.metric_code, []).append(obs)

        for metric_code in sorted(by_metric):
            metric_obs = sorted(by_metric[metric_code], key=lambda o: o.observed_at)
            first = metric_obs[0]
            group = groups[(first.category, first.system)]
            if first.value_type == "numeric":
                summary = self._summarize_numeric(metric_obs)
                group.numeric.append(summary)
                abnormalities.extend(self._numeric_abnormalities(metric_obs, summary))
            elif first.value_type == "qualitative":
                summary = self._summarize_qualitative(metric_obs)
                group.qualitative.append(summary)
                abnormalities.extend(self._qualitative_abnormalities(metric_obs, summary))
            else:
                group.text.append(self._summarize_text(metric_obs))

        return CrossSystemSummary(
            version=self.VERSION,
            as_of=decision_date,
            groups=[groups[key] for key in sorted(groups)],
            abnormalities=sorted(
                abnormalities,
                key=lambda a: (a.metric_code, a.observed_at, a.direction, a.record_ref),
            ),
            excluded_future_count=len(future),
            excluded_record_refs=sorted(o.record_ref for o in future),
            notes=notes,
        )

    # ---- 未来数据 ----

    def _split_future(
        self, observations: list[Observation], as_of: date
    ) -> tuple[list[Observation], list[Observation]]:
        usable: list[Observation] = []
        future: list[Observation] = []
        for obs in observations:
            if obs.observed_at > as_of:
                future.append(obs)
            else:
                usable.append(obs)
        return usable, future

    # ---- 数值 ----

    def _summarize_numeric(self, metric_obs: list[Observation]) -> NumericMetricSummary:
        first = metric_obs[0]
        units = {self._norm_unit(o.unit) for o in metric_obs if o.unit}
        unit_consistent = len(units) <= 1

        timeline = [
            TimelinePoint(
                observed_at=o.observed_at,
                value=o.canonical_value if o.canonical_value is not None else 0.0,
                unit=o.unit,
                reference_min=o.reference_min,
                reference_max=o.reference_max,
                reference_source=o.reference_source,
                reference_population=o.reference_population,
                direction=self._numeric_direction(o),
                record_ref=o.record_ref,
                report_flag=o.report_flag,
            )
            for o in metric_obs
            if o.canonical_value is not None
        ]

        comparability = "comparable"
        reason: str | None = None
        if not unit_consistent:
            comparability = "incomparable_unit"
            reason = "历史记录单位不一致（未登记换算依据），不做跨记录趋势比较"
        elif len(timeline) < 2:
            comparability = "single_observation"
            reason = "仅一条有效数值，不推断趋势"

        trend = MetricTrend.UNKNOWN.value
        trend_reason: str | None = None
        if comparability == "comparable":
            assessment = self._trend_engine.assess(
                self._to_metric_observations(metric_obs), self._trend_config
            )
            trend = assessment.trend.value
            trend_reason = assessment.reason

        return NumericMetricSummary(
            metric_code=first.metric_code,
            display_name=first.display_name,
            category=first.category,
            system=first.system,
            comparability=comparability,
            comparability_reason=reason,
            trend=trend,
            trend_reason=trend_reason,
            unit=first.unit,
            timeline=timeline,
            abnormality_count=sum(1 for p in timeline if p.direction in ("high", "low")),
        )

    def _to_metric_observations(self, metric_obs: list[Observation]) -> list[MetricObservation]:
        return [
            MetricObservation(
                source_id=o.record_ref,
                metric_code=o.metric_code,
                canonical_name=o.display_name,
                observed_at=o.observed_at,
                value=o.canonical_value,
                status=MetricStatus.NORMAL,
                standard_unit=o.unit,
                category=o.category,
            )
            for o in metric_obs
            if o.canonical_value is not None
        ]

    def _numeric_direction(self, obs: Observation) -> str:
        if obs.canonical_value is None:
            return "no_reference"
        if obs.reference_min is None and obs.reference_max is None:
            return "no_reference"
        if obs.reference_max is not None and obs.canonical_value > obs.reference_max:
            return "high"
        if obs.reference_min is not None and obs.canonical_value < obs.reference_min:
            return "low"
        return "normal"

    def _numeric_abnormalities(
        self, metric_obs: list[Observation], summary: NumericMetricSummary
    ) -> list[AbnormalityItem]:
        items: list[AbnormalityItem] = []
        for point in summary.timeline:
            if point.direction not in ("high", "low"):
                continue
            obs = next(o for o in metric_obs if o.record_ref == point.record_ref)
            bound = obs.reference_max if point.direction == "high" else obs.reference_min
            operator = "≤" if point.direction == "high" else "≥"
            items.append(
                AbnormalityItem(
                    metric_code=summary.metric_code,
                    display_name=summary.display_name,
                    observed_at=point.observed_at,
                    direction=point.direction,
                    value_text=self._value_text(point.value),
                    unit=point.unit,
                    reference_text=(
                        f"{point.direction}: {'上限' if point.direction == 'high' else '下限'}"
                        f" {self._value_text(bound)} {operator}（当次参考区间）"
                    ),
                    reference_source=point.reference_source,
                    reference_population=point.reference_population,
                    record_ref=point.record_ref,
                )
            )
        return items

    # ---- 定性 ----

    def _summarize_qualitative(self, metric_obs: list[Observation]) -> QualitativeMetricSummary:
        first = metric_obs[0]
        timeline: list[QualitativeTimelineEntry] = []
        for obs in metric_obs:
            status = obs.qualitative_status or obs.raw_value
            if obs.expected_qualitative is not None:
                direction = (
                    "normal" if status == obs.expected_qualitative else "abnormal"
                )
            else:
                direction = "no_reference"
            timeline.append(
                QualitativeTimelineEntry(
                    observed_at=obs.observed_at,
                    status=status,
                    expected=obs.expected_qualitative,
                    reference_source=obs.reference_source,
                    direction=direction,
                    record_ref=obs.record_ref,
                    report_flag=obs.report_flag,
                )
            )
        return QualitativeMetricSummary(
            metric_code=first.metric_code,
            display_name=first.display_name,
            category=first.category,
            system=first.system,
            timeline=timeline,
            abnormality_count=sum(1 for e in timeline if e.direction == "abnormal"),
        )

    def _qualitative_abnormalities(
        self, metric_obs: list[Observation], summary: QualitativeMetricSummary
    ) -> list[AbnormalityItem]:
        items: list[AbnormalityItem] = []
        for entry in summary.timeline:
            if entry.direction != "abnormal":
                continue
            items.append(
                AbnormalityItem(
                    metric_code=summary.metric_code,
                    display_name=summary.display_name,
                    observed_at=entry.observed_at,
                    direction="qualitative_mismatch",
                    value_text=entry.status,
                    unit=None,
                    reference_text=f"期望定性结果：{entry.expected}",
                    reference_source=entry.reference_source,
                    reference_population=None,
                    record_ref=entry.record_ref,
                )
            )
        return items

    # ---- 文字 ----

    def _summarize_text(self, metric_obs: list[Observation]) -> TextMetricSummary:
        first = metric_obs[0]
        return TextMetricSummary(
            metric_code=first.metric_code,
            display_name=first.display_name,
            category=first.category,
            system=first.system,
            timeline=[
                TextTimelineEntry(
                    observed_at=o.observed_at,
                    text=o.text_value or o.raw_value,
                    record_ref=o.record_ref,
                    report_flag=o.report_flag,
                )
                for o in metric_obs
            ],
        )

    # ---- 工具 ----

    def _norm_unit(self, unit: str | None) -> str:
        return (unit or "").strip().lower()

    def _value_text(self, value: float | None) -> str:
        if value is None:
            return "-"
        if float(value).is_integer():
            return str(int(value))
        return f"{value:g}"
