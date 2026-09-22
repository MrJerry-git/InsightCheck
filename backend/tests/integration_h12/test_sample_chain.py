"""H12 自制样例 × H01/H03/H05/H07 全链路联调。

链路：自制样例文件 → H03 表格解析（H01 字典映射）→ H05 跨系统汇总
→ H02 关联目录 → H07 规则候选。演示行数据如何进入统一流程，
供 T04（分析编排）/T05（候选汇总）/T10（问答上下文）对接参考。
所有样例均为自制工程样例（非真实数据）。
"""

import csv
from datetime import date
from pathlib import Path

import pytest

from app.cross_system import CrossSystemSummarizer, Observation
from app.exam_dictionary import (
    ExamDictionary,
    FindingCatalog,
    load_builtin_associations,
    load_builtin_catalog,
)
from app.rule_candidates import (
    NormalizedFinding,
    PatientContext,
    RuleCandidateService,
)
from app.tabular_parsing import TabularReportParser

SAMPLES_DIR = Path(__file__).parents[1] / "fixtures" / "h12_samples"
AS_OF = date(2026, 9, 21)


def read_rows(name: str) -> list[dict[str, str]]:
    with (SAMPLES_DIR / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_lines(name: str) -> list[str]:
    return (SAMPLES_DIR / name).read_text(encoding="utf-8").splitlines()


@pytest.fixture(scope="module")
def dictionary() -> ExamDictionary:
    return load_builtin_catalog()


@pytest.fixture(scope="module")
def parser(dictionary: ExamDictionary) -> TabularReportParser:
    return TabularReportParser(dictionary)


# ---- 样例 → 解析 ----


def test_blood_routine_sample_parses_fully_mapped(parser: TabularReportParser) -> None:
    report = parser.parse("h12_blood_routine.csv", read_rows("h12_blood_routine.csv"))
    assert report.issues == []
    assert report.unmapped == []
    assert all(e.status == "mapped" for e in report.entries)
    codes = {e.canonical_code for e in report.entries}
    assert "6690-2" in codes and "718-7" in codes


def test_urine_stool_sample_covers_qualitative_and_text(parser: TabularReportParser) -> None:
    report = parser.parse("h12_urine_stool.csv", read_rows("h12_urine_stool.csv"))
    statuses = {e.raw_name: e for e in report.entries}
    assert statuses["尿蛋白定性"].qualitative_status == "±"
    assert statuses["尿沉渣镜检"].text_value == "未见明显异常"
    # 便潜血"+"不在登记允许值（阴性/弱阳性/阳性）内 → 保留原文进入待确认
    stool = statuses["便潜血定性"]
    assert stool.status == "unregistered_qualitative"
    assert any(u.reason == "qualitative_value_not_registered" for u in report.unmapped)


def test_biochemistry_sample_flags_unconverted_unit(parser: TabularReportParser) -> None:
    report = parser.parse(
        "h12_biochemistry_lipids.csv", read_rows("h12_biochemistry_lipids.csv")
    )
    entries = {e.raw_name: e for e in report.entries}
    # 血糖/尿酸偏高条目 mapped，且异常提示列保留
    assert entries["空腹血糖"].report_hint == "偏高"
    assert entries["空腹血糖"].status == "mapped"
    # 参考区间带 <、≥ 等前缀：原样保留，不做猜测解析
    assert entries["总胆固醇"].raw_reference == "<5.2"
    # 样例中没有需要换算的单位 → 全部 mapped
    assert all(e.status != "unit_unconverted" for e in report.entries)


def test_unknown_metric_sample_queues_without_dropping(parser: TabularReportParser) -> None:
    report = parser.parse("h12_unknown_metrics.csv", read_rows("h12_unknown_metrics.csv"))
    names = [u.raw_name for u in report.unmapped]
    assert "血浆D-二聚体" in names and "超敏C反应蛋白" in names
    assert len(report.entries) == 3  # 条目保留，不丢弃


# ---- 样例 → 跨系统汇总 ----


def build_observations(
    report, exam_date: date, dictionary: ExamDictionary | None = None
) -> list[Observation]:
    """演示：解析结果 → H05 输入（T04 编排层的对接样例）。

    类别/系统来自 H01 字典条目；真实系统中由 T02 存储的记录携带。
    """
    observations: list[Observation] = []
    for entry in report.entries:
        if entry.canonical_code is None:
            continue
        catalog_entry = dictionary.lookup_by_code(entry.canonical_code) if dictionary else None
        category = catalog_entry.category if catalog_entry else "uncategorized"
        system = catalog_entry.system if catalog_entry else "general"
        common = dict(
            metric_code=entry.canonical_code,
            display_name=entry.raw_name,
            observed_at=exam_date,
            record_ref=f"{report.source_name}:{entry.row_index}",
            raw_value=entry.raw_value,
            report_flag=entry.report_hint,
            category=category,
            system=system,
        )
        if entry.value_type == "numeric":
            common.update(
                value_type="numeric",
                canonical_value=entry.canonical_value,
                unit=entry.canonical_unit,
            )
        elif entry.value_type == "qualitative":
            common.update(
                value_type="qualitative",
                qualitative_status=entry.qualitative_status or entry.text_value,
            )
        else:
            common.update(value_type="text", text_value=entry.text_value)
        observations.append(Observation(**common))
    return observations


def test_blood_routine_sample_flows_through_summarizer(
    parser: TabularReportParser, dictionary: ExamDictionary
) -> None:
    report = parser.parse("h12_blood_routine.csv", read_rows("h12_blood_routine.csv"))
    summary = CrossSystemSummarizer().summarize(
        build_observations(report, date(2026, 6, 1), dictionary), as_of=AS_OF
    )
    # 样例未携带参考区间 → 全部 no_reference（不编造阈值），数值罗列正常
    assert summary.abnormalities == []
    group = summary.groups[0]
    assert group.category == "blood_routine"
    assert len(group.numeric) >= 4


def test_biochemistry_sample_flags_abnormalities_from_report_hint(
    parser: TabularReportParser, dictionary: ExamDictionary
) -> None:
    """样例无参考区间明细：汇总不判定异常（no_reference）。

    带参考区间的判定路径由 tests/cross_system 与 H05 单元覆盖；
    真实报告的"偏高"提示列保留为 report_flag 供人工与规则使用。
    """
    report = parser.parse(
        "h12_biochemistry_lipids.csv", read_rows("h12_biochemistry_lipids.csv")
    )
    summary = CrossSystemSummarizer().summarize(
        build_observations(report, date(2026, 7, 1), dictionary), as_of=AS_OF
    )
    assert summary.abnormalities == []
    hints = [
        o.report_flag
        for o in build_observations(report, date(2026, 7, 1), dictionary)
        if o.report_flag
    ]
    assert "偏高" in hints


# ---- 样例 → 关联目录 → 规则候选 ----


def findings_from_abnormalities(
    summary, catalog: FindingCatalog
) -> list[NormalizedFinding]:
    """演示：H05 异常清单 → H02 关联 → H07 发现输入（T05 对接样例）。"""
    findings: list[NormalizedFinding] = []
    for item in summary.abnormalities:
        for association in catalog.associations_for_exam(item.metric_code):
            if association.direction not in ("any", item.direction):
                continue
            findings.append(
                NormalizedFinding(
                    finding_id=f"{item.record_ref}:{association.association_id}",
                    exam_code=item.metric_code,
                    direction=item.direction,
                    condition_code=association.condition_code,
                    condition_name=association.condition_name,
                    value_text=item.value_text,
                    record_ref=item.record_ref,
                    observed_at=item.observed_at,
                )
            )
    return findings


def test_high_glucose_with_reference_drives_rule_candidates(
    parser: TabularReportParser, dictionary: ExamDictionary
) -> None:
    """带参考区间的血糖样例走通：解析→汇总→关联→候选。"""
    # 演示带当次参考区间的输入（真实系统中来自字典登记区间）
    glucose_rows = [
        {"项目": "空腹血糖", "结果": "6.8", "单位": "mmol/L", "参考区间": "3.9-6.1", "提示": "偏高"}
    ]
    report = parser.parse("glucose_recheck.csv", glucose_rows)
    observations = build_observations(report, date(2026, 7, 1))
    for obs in observations:
        if obs.metric_code == "1558-6":
            object.__setattr__(
                obs,
                "reference_max",
                6.1,
            )
            object.__setattr__(
                obs,
                "reference_min",
                3.9,
            )
            object.__setattr__(
                obs,
                "reference_source",
                "WS/T 404-2012《临床常用生化检验项目参考区间》",
            )
            object.__setattr__(obs, "reference_population", "成人（空腹 ≥8h）")
    summary = CrossSystemSummarizer().summarize(observations, as_of=AS_OF)
    assert [a.direction for a in summary.abnormalities] == ["high"]

    catalog = load_builtin_associations()
    findings = findings_from_abnormalities(summary, catalog)
    assert findings, "血糖升高应命中 H02 关联"
    result = RuleCandidateService().candidates(
        findings, PatientContext(sex="male", age=45), include_drafts=True
    )
    codes = [c.exam_code for c in result.candidates]
    assert "4548-4" in codes  # 糖化血红蛋白复查候选
    assert all("6.8" in reason for c in result.candidates for reason in c.reasons)


def test_text_samples_feed_summarizer_without_judgment(
    dictionary: ExamDictionary,
) -> None:
    """文字类样例（心电图/超声）按行进汇总：时间线对照，不判定。"""
    ecg_text = "\n".join(read_lines("h12_ecg_report.txt"))
    us_text = "\n".join(read_lines("h12_thyroid_us.txt"))
    observations = [
        Observation(
            metric_code="IC:M-ECG-CONCLUSION",
            display_name="心电图结论",
            value_type="text",
            observed_at=date(2026, 5, 1),
            record_ref="h12_ecg_report.txt",
            category="ecg_function",
            system="circulatory",
            text_value=ecg_text,
        ),
        Observation(
            metric_code="IC:M-IMG-CONCLUSION",
            display_name="影像结论",
            value_type="text",
            observed_at=date(2026, 8, 1),
            record_ref="h12_thyroid_us.txt",
            category="imaging",
            system="endocrine",
            text_value=us_text,
        ),
    ]
    summary = CrossSystemSummarizer().summarize(observations, as_of=AS_OF)
    assert summary.abnormalities == []
    text_metrics = [t for g in summary.groups for t in g.text]
    assert len(text_metrics) == 2


def test_full_chain_is_deterministic(
    parser: TabularReportParser, dictionary: ExamDictionary
) -> None:
    """同输入同输出：全链路两次执行结果一致。"""
    rows = read_rows("h12_biochemistry_lipids.csv")

    def run() -> dict:
        report = parser.parse("h12_biochemistry_lipids.csv", rows)
        summary = CrossSystemSummarizer().summarize(
            build_observations(report, date(2026, 7, 1), dictionary), as_of=AS_OF
        )
        return summary.as_dict()

    assert run() == run()


def test_sample_files_declared_in_coverage_doc() -> None:
    """覆盖清单与样例文件一一对应（清单驱动验收）。"""
    doc = (
        Path(__file__).parents[3]
        / "docs"
        / "SAMPLE_COVERAGE.md"
    ).read_text(encoding="utf-8")
    for name in (
        "h12_blood_routine.csv",
        "h12_urine_stool.csv",
        "h12_biochemistry_lipids.csv",
        "h12_unknown_metrics.csv",
        "h12_ecg_report.txt",
        "h12_thyroid_us.txt",
    ):
        assert name in doc, f"覆盖清单缺少 {name}"
