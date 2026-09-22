"""H05 跨系统趋势及异常整理：数值趋势、定性时间线、文字对照与异常判定。"""

from __future__ import annotations

from datetime import date

from app.cross_system import CrossSystemSummarizer, Observation


def obs(
    code: str,
    value: float,
    observed: date,
    *,
    unit: str | None = "10*9/L",
    ref_min: float | None = 3.5,
    ref_max: float | None = 9.5,
    source: str | None = "WS/T 405-2012",
    population: str | None = "成人",
    record: str | None = None,
    name: str = "白细胞计数",
    category: str = "blood_routine",
    system: str = "hematology",
) -> Observation:
    return Observation(
        metric_code=code,
        display_name=name,
        value_type="numeric",
        observed_at=observed,
        record_ref=record or f"rec-{code}-{observed.isoformat()}",
        category=category,
        system=system,
        raw_value=str(value),
        canonical_value=value,
        unit=unit,
        reference_min=ref_min,
        reference_max=ref_max,
        reference_source=source,
        reference_population=population,
    )


def test_numeric_trend_with_reference_provenance() -> None:
    summarizer = CrossSystemSummarizer()
    summary = summarizer.summarize(
        [
            obs("6690-2", 6.0, date(2024, 3, 1)),
            obs("6690-2", 6.1, date(2025, 3, 1)),
            obs("6690-2", 6.05, date(2026, 3, 1)),
        ],
        as_of=date(2026, 9, 20),
    )
    group = summary.groups[0]
    assert group.category == "blood_routine"
    metric = group.numeric[0]
    assert metric.comparability == "comparable"
    assert metric.trend in ("STABLE", "RISING", "FALLING", "FLUCTUATING", "UNKNOWN")
    assert metric.timeline[0].reference_source == "WS/T 405-2012"
    assert metric.timeline[0].reference_population == "成人"
    assert all(p.direction == "normal" for p in metric.timeline)
    assert summary.abnormalities == []


def test_abnormality_high_and_low_cite_current_reference() -> None:
    summarizer = CrossSystemSummarizer()
    summary = summarizer.summarize(
        [
            obs("6690-2", 12.0, date(2026, 1, 10)),
            obs("6690-2", 2.9, date(2026, 5, 10)),
        ],
        as_of=date(2026, 9, 20),
    )
    high, low = summary.abnormalities[0], summary.abnormalities[1]
    assert high.direction == "high" and high.value_text == "12"
    assert "9.5" in high.reference_text and high.reference_source == "WS/T 405-2012"
    assert low.direction == "low" and low.value_text == "2.9"
    assert "3.5" in low.reference_text


def test_missing_reference_is_not_judged() -> None:
    summarizer = CrossSystemSummarizer()
    summary = summarizer.summarize(
        [obs("6690-2", 99.0, date(2026, 1, 1), ref_min=None, ref_max=None, source=None)],
        as_of=date(2026, 9, 20),
    )
    assert summary.abnormalities == []
    assert summary.groups[0].numeric[0].timeline[0].direction == "no_reference"


def test_inconsistent_units_marked_incomparable_no_trend() -> None:
    summarizer = CrossSystemSummarizer()
    summary = summarizer.summarize(
        [
            obs("718-7", 135.0, date(2024, 1, 1), unit="g/L", name="血红蛋白"),
            obs("718-7", 13.5, date(2025, 1, 1), unit="g/dL", name="血红蛋白"),
        ],
        as_of=date(2026, 9, 20),
    )
    metric = summary.groups[0].numeric[0]
    assert metric.comparability == "incomparable_unit"
    assert metric.trend == "UNKNOWN"
    assert metric.trend_reason is None
    assert metric.comparability_reason and "单位不一致" in metric.comparability_reason
    # 时间线仍完整保留，不丢数据
    assert len(metric.timeline) == 2


def test_single_observation_degrades_gracefully() -> None:
    summarizer = CrossSystemSummarizer()
    summary = summarizer.summarize(
        [obs("6690-2", 6.2, date(2026, 3, 1))], as_of=date(2026, 9, 20)
    )
    metric = summary.groups[0].numeric[0]
    assert metric.comparability == "single_observation"
    assert metric.trend == "UNKNOWN"
    assert metric.trend_reason is None
    assert metric.comparability_reason and "仅一条" in metric.comparability_reason


def test_qualitative_timeline_with_expected_value() -> None:
    protein = Observation(
        metric_code="20454-5",
        display_name="尿蛋白定性",
        value_type="qualitative",
        observed_at=date(2025, 6, 1),
        record_ref="urine-2025",
        category="urine_stool",
        system="urinary",
        raw_value="++",
        qualitative_status="++",
        expected_qualitative="阴性",
        reference_source="检验科登记区间",
    )
    protein_ok = Observation(
        metric_code="20454-5",
        display_name="尿蛋白定性",
        value_type="qualitative",
        observed_at=date(2026, 6, 1),
        record_ref="urine-2026",
        category="urine_stool",
        system="urinary",
        raw_value="阴性",
        qualitative_status="阴性",
        expected_qualitative="阴性",
        reference_source="检验科登记区间",
    )
    summary = CrossSystemSummarizer().summarize(
        [protein, protein_ok], as_of=date(2026, 9, 20)
    )
    metric = summary.groups[0].qualitative[0]
    assert [e.status for e in metric.timeline] == ["++", "阴性"]
    assert metric.abnormality_count == 1
    abnormal = summary.abnormalities[0]
    assert abnormal.direction == "qualitative_mismatch"
    assert abnormal.reference_text == "期望定性结果：阴性"


def test_qualitative_without_expected_is_not_judged() -> None:
    item = Observation(
        metric_code="IC:EX-HP-BREATH",
        display_name="幽门螺杆菌呼气试验",
        value_type="qualitative",
        observed_at=date(2026, 4, 1),
        record_ref="hp-2026",
        category="extended",
        system="digestive",
        raw_value="阳性",
        qualitative_status="阳性",
    )
    summary = CrossSystemSummarizer().summarize([item], as_of=date(2026, 9, 20))
    assert summary.abnormalities == []
    assert summary.groups[0].qualitative[0].timeline[0].direction == "no_reference"


def test_text_conclusions_kept_in_order_without_judgment() -> None:
    ecg_2024 = Observation(
        metric_code="IC:M-ECG-CONCLUSION",
        display_name="心电图结论",
        value_type="text",
        observed_at=date(2024, 5, 1),
        record_ref="ecg-2024",
        category="ecg_function",
        system="circulatory",
        text_value="窦性心律",
    )
    ecg_2026 = Observation(
        metric_code="IC:M-ECG-CONCLUSION",
        display_name="心电图结论",
        value_type="text",
        observed_at=date(2026, 5, 1),
        record_ref="ecg-2026",
        category="ecg_function",
        system="circulatory",
        text_value="窦性心律，ST-T 未见动态改变",
    )
    summary = CrossSystemSummarizer().summarize([ecg_2026, ecg_2024], as_of=date(2026, 9, 20))
    metric = summary.groups[0].text[0]
    assert [e.text for e in metric.timeline] == ["窦性心律", "窦性心律，ST-T 未见动态改变"]
    assert metric.timeline[0].record_ref == "ecg-2024"
    assert summary.abnormalities == []


def test_future_observations_are_excluded_with_trace() -> None:
    summarizer = CrossSystemSummarizer()
    summary = summarizer.summarize(
        [
            obs("6690-2", 6.2, date(2026, 3, 1), record="rec-past"),
            obs("6690-2", 99.0, date(2027, 3, 1), record="rec-future"),
        ],
        as_of=date(2026, 9, 20),
    )
    assert summary.excluded_future_count == 1
    assert summary.excluded_record_refs == ["rec-future"]
    assert summary.notes and "排除" in summary.notes[0]
    metric = summary.groups[0].numeric[0]
    assert [p.record_ref for p in metric.timeline] == ["rec-past"]


def test_groups_sorted_and_mixed_value_types_stay_separate() -> None:
    liver_text = Observation(
        metric_code="IC:M-PE-INTERNAL",
        display_name="内科检查结论",
        value_type="text",
        observed_at=date(2026, 3, 1),
        record_ref="pe-1",
        category="physical_exam",
        system="general",
        text_value="腹部平软，无压痛",
    )
    alt = obs(
        "1742-6",
        65.0,
        date(2026, 3, 1),
        unit="U/L",
        ref_min=9,
        ref_max=50,
        name="丙氨酸氨基转移酶",
        category="biochemistry",
        system="hepatobiliary",
    )
    summary = CrossSystemSummarizer().summarize([alt, liver_text], as_of=date(2026, 9, 20))
    assert [(g.category, g.system) for g in summary.groups] == [
        ("biochemistry", "hepatobiliary"),
        ("physical_exam", "general"),
    ]
    assert summary.abnormalities[0].metric_code == "1742-6"


def test_empty_input_returns_empty_summary() -> None:
    summary = CrossSystemSummarizer().summarize([], as_of=date(2026, 9, 20))
    assert summary.groups == []
    assert summary.abnormalities == []
    assert summary.version == "cross-system-summary-v1"
