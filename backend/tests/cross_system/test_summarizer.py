"""H05 跨系统趋势及异常整理：数值趋势、定性时间线、文字对照与异常判定。"""

from __future__ import annotations

from dataclasses import dataclass
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


# ---- PR #21 审核 P1：缺单位不得被判为可比较 ----


def test_missing_unit_is_not_comparable() -> None:
    """审核复现：2024 年 6 (10*9/L)、2025 年 60 (unit=None) 曾被判 comparable/RISING。"""
    summarizer = CrossSystemSummarizer()
    summary = summarizer.summarize(
        [
            obs("6690-2", 6.0, date(2024, 6, 1), unit="10*9/L"),
            obs("6690-2", 60.0, date(2025, 6, 1), unit=None),
        ],
        as_of=date(2026, 9, 20),
    )
    metric = summary.groups[0].numeric[0]
    assert metric.comparability == "missing_unit"
    assert metric.trend == "UNKNOWN", "缺单位时不能推断上升趋势"
    assert metric.trend_reason is None
    assert metric.comparability_reason and "缺少单位" in metric.comparability_reason
    assert len(metric.timeline) == 2, "时间线必须保留，不能丢数据"
    assert metric.missing_unit_refs == ["rec-6690-2-2025-06-01"]


def test_blank_unit_is_treated_as_missing() -> None:
    summarizer = CrossSystemSummarizer()
    summary = summarizer.summarize(
        [
            obs("6690-2", 6.0, date(2024, 6, 1), unit="10*9/L"),
            obs("6690-2", 60.0, date(2025, 6, 1), unit="   "),
        ],
        as_of=date(2026, 9, 20),
    )
    assert summary.groups[0].numeric[0].comparability == "missing_unit"


def test_missing_unit_recorded_for_follow_up_question() -> None:
    summarizer = CrossSystemSummarizer()
    summary = summarizer.summarize(
        [
            obs("718-7", 135.0, date(2024, 1, 1), unit="g/L", name="血红蛋白"),
            obs("718-7", 13.5, date(2025, 1, 1), unit=None, name="血红蛋白"),
        ],
        as_of=date(2026, 9, 20),
    )
    assert len(summary.missing_units) == 1
    item = summary.missing_units[0]
    assert item.metric_code == "718-7"
    assert item.record_refs == ("rec-718-7-2025-01-01",)
    assert item.observed_at == (date(2025, 1, 1),)
    assert "缺少单位" in item.question
    assert any("缺少单位" in note for note in summary.notes)
    payload = summary.as_dict()
    assert payload["missing_units"][0]["record_refs"] == ["rec-718-7-2025-01-01"]


def test_h03_unit_missing_entry_does_not_create_trend() -> None:
    """H03→H05 跨模块：H03 标 unit_missing 的条目不得被传播成趋势或异常。"""

    def from_parsed_h03(parsed: dict, observed: date) -> Observation:
        """T03 入库前按 H03 契约构造观测：不可比较状态不生成 canonical_value。"""
        non_comparable = parsed["status"] in ("unit_missing", "unit_unconverted", "invalid_value")
        return Observation(
            metric_code="6690-2",
            display_name="白细胞计数",
            value_type="numeric",
            observed_at=observed,
            record_ref=f"parsed-{observed.isoformat()}",
            category="blood_routine",
            system="hematology",
            raw_value=parsed["raw_value"],
            canonical_value=None if non_comparable else parsed["canonical_value"],
            unit=parsed["canonical_unit"],
        )

    summary = CrossSystemSummarizer().summarize(
        [
            from_parsed_h03(
                {"status": "mapped", "canonical_value": 6.0, "canonical_unit": "10*9/L",
                 "raw_value": "6.0"},
                date(2024, 6, 1),
            ),
            from_parsed_h03(
                {"status": "unit_missing", "canonical_value": None, "canonical_unit": None,
                 "raw_value": "60"},
                date(2025, 6, 1),
            ),
        ],
        as_of=date(2026, 9, 20),
    )
    metric = summary.groups[0].numeric[0]
    assert metric.comparability == "missing_unit"
    assert metric.trend == "UNKNOWN"
    assert len(metric.timeline) == 1, "缺单位条目不能进入可比较时间线"
    assert metric.missing_unit_refs == ["parsed-2025-06-01"]
    # 缺单位记录必须被登记为待确认项（含原值），AI 才能追问补齐
    assert len(summary.missing_units) == 1
    assert summary.missing_units[0].records[0].raw_value == "60"
    assert summary.missing_units[0].observed_at == (date(2025, 6, 1),)
    assert any("缺少单位" in note for note in summary.notes)
    assert summary.abnormalities == []


def test_raw_numeric_without_canonical_is_still_surfaced() -> None:
    """复核复现：raw_value='60'、canonical_value=None、unit=None 时不得漏检。"""
    summary = CrossSystemSummarizer().summarize(
        [
            Observation(
                metric_code="6690-2",
                display_name="白细胞计数",
                value_type="numeric",
                observed_at=date(2025, 6, 1),
                record_ref="raw-only-2025",
                category="blood_routine",
                system="hematology",
                raw_value="60",
                canonical_value=None,
                unit=None,
            )
        ],
        as_of=date(2026, 9, 20),
    )
    metric = summary.groups[0].numeric[0]
    assert metric.comparability == "missing_unit"
    assert metric.timeline == [], "无可比较数值时不生成时间线点"
    assert metric.missing_unit_refs == ["raw-only-2025"]
    assert len(summary.missing_units) == 1
    assert summary.missing_units[0].records[0].raw_value == "60"
    assert summary.missing_units[0].observed_at == (date(2025, 6, 1),)
    assert summary.notes and "缺少单位" in summary.notes[0]


def test_confirmed_units_remain_comparable() -> None:
    summarizer = CrossSystemSummarizer()
    summary = summarizer.summarize(
        [
            obs("6690-2", 6.0, date(2024, 6, 1), unit="10*9/L"),
            obs("6690-2", 6.2, date(2025, 6, 1), unit="10*9/L"),
        ],
        as_of=date(2026, 9, 20),
    )
    metric = summary.groups[0].numeric[0]
    assert metric.comparability == "comparable"
    assert metric.missing_unit_refs == []
    assert summary.missing_units == []


# ---- PR #21 复核 P1：真实 H03 → H05 跨模块（调用真实解析器，非模拟） ----


@dataclass(frozen=True)
class _FakeConversion:
    from_unit: str
    to_unit: str
    factor: float
    offset: float
    basis: str


@dataclass(frozen=True)
class _FakeDictEntry:
    code: str
    display_name: str
    value_type: str
    standard_unit: str | None = None
    unit_conversions: tuple[_FakeConversion, ...] = ()
    qualitative_values: tuple[str, ...] = ()


class _FakeDictionary:
    """H03 字典桩：只实现 TabularReportParser 需要的 lookup 接口。"""

    def __init__(self, entries: dict[str, _FakeDictEntry]) -> None:
        self._entries = {k.strip().casefold(): v for k, v in entries.items()}

    def lookup(self, raw_name: str):
        return self._entries.get((raw_name or "").strip().casefold())


def _h03_to_h05_observations(
    rows: list[dict[str, str]], observed_dates: list[date]
) -> tuple[object, list[Observation]]:
    """真实调用 H03 解析器，再按 T03 边界把条目映射成 H05 观测。

    返回 (ParsedTabularReport, [Observation])。映射只搬运字段，不再补单位或
    任何标准化——标准化是 H03 的职责，H05 必须消费 H03 的真实输出。
    """
    from app.tabular_parsing import TabularReportParser

    dictionary = _FakeDictionary(
        {
            "白细胞计数": _FakeDictEntry(
                code="6690-2", display_name="白细胞计数", value_type="numeric",
                standard_unit="10*9/L",
            ),
            "血红蛋白": _FakeDictEntry(
                code="718-7", display_name="血红蛋白", value_type="numeric", standard_unit="g/L",
            ),
        }
    )
    report = TabularReportParser(dictionary).parse("lab.csv", rows)
    observations = [
        Observation(
            metric_code=entry.canonical_code or entry.raw_name,
            display_name=entry.raw_name,
            value_type=entry.value_type,
            observed_at=observed,
            record_ref=f"h03-{entry.row_index}",
            category="blood_routine",
            system="hematology",
            raw_value=entry.raw_value,
            canonical_value=entry.canonical_value,
            unit=entry.canonical_unit,
        )
        for entry, observed in zip(report.entries, observed_dates, strict=True)
    ]
    return report, observations


def test_real_h03_to_h05_missing_unit_is_surfaced_for_follow_up() -> None:
    """真实 H03→H05：H03 判 unit_missing 的记录必须进入 H05 待确认单位登记。

    复核复现：H03 对缺单位记录返回 canonical_value=None、保留 raw_value，
    H05 若只从可比记录派生 missing_unit 会漏掉它。这里跑真实 H03 解析器，
    验证原值/日期/来源被保留且不产生趋势或异常。
    """
    rows = [
        {"项目": "白细胞计数", "结果": "6.0", "单位": "10*9/L"},
        {"项目": "白细胞计数", "结果": "60", "单位": ""},
    ]
    report, observations = _h03_to_h05_observations(
        rows, [date(2024, 6, 1), date(2025, 6, 1)]
    )
    # H03 侧：缺单位条目被标 unit_missing、不生成可比较数值、原值保留
    missing = report.entries[1]
    assert missing.status == "unit_missing"
    assert missing.canonical_value is None
    assert missing.raw_value == "60"
    assert missing.unit_confirmation_required is True

    summary = CrossSystemSummarizer().summarize(observations, as_of=date(2026, 9, 20))
    metric = summary.groups[0].numeric[0]
    assert metric.comparability == "missing_unit"
    assert metric.trend == "UNKNOWN"
    assert metric.missing_unit_refs == ["h03-2"]
    assert len(metric.timeline) == 1, "缺单位记录不能进入可比较时间线"
    assert len(summary.missing_units) == 1
    item = summary.missing_units[0]
    assert item.record_refs == ("h03-2",)
    assert item.records[0].raw_value == "60"
    assert item.records[0].observed_at == date(2025, 6, 1)
    assert any("缺少单位" in note for note in summary.notes)
    assert summary.abnormalities == []


def test_real_h03_to_h05_consistent_units_stay_comparable() -> None:
    """真实 H03→H05：单位齐备时不得被误判为缺单位，趋势照常计算。"""
    rows = [
        {"项目": "白细胞计数", "结果": "6.0", "单位": "10*9/L"},
        {"项目": "白细胞计数", "结果": "6.1", "单位": "10*9/L"},
    ]
    report, observations = _h03_to_h05_observations(
        rows, [date(2024, 6, 1), date(2025, 6, 1)]
    )
    assert all(e.status == "mapped" for e in report.entries)
    summary = CrossSystemSummarizer().summarize(observations, as_of=date(2026, 9, 20))
    metric = summary.groups[0].numeric[0]
    assert metric.comparability == "comparable"
    assert metric.missing_unit_refs == []
    assert summary.missing_units == []
    assert len(metric.timeline) == 2


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
