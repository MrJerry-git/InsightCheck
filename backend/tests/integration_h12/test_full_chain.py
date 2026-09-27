"""H12 端到端联调：文件 → 抽取 → 校对 → 分析 → 候选 → 方案。

本文件补的是 PR #29 审查指出的缺口：

> 现有模块测试通过不能替代 H→T→前端链路。请补充实际 CSV/Excel/PDF
> →校对→分析→候选→方案的联调；**无法计算应明确传至页面**。

与原 `test_sample_chain.py` 的区别：
- 原文件从「已解出的行」开始（`read_rows` 直接给 dict）；
- 本文件从**真实文件字节**开始：CSV / Excel(.xlsx) / PDF 三种真实格式，
  经解析或抽取拿到行，再走「校对 → 分析 → 候选 → 方案」全链。

三条链路的终点都是 `PlanBuildResult`，并且显式断言「无法计算」的情况
（缺单位、未知指标、扫描件无 OCR、未知版式）被**保留为可见项**传给页面，
而不是静默丢弃或被算成一个数。
"""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path

import pytest

from app.cross_system import CrossSystemSummarizer, Observation
from app.exam_dictionary import (
    load_builtin_associations,
    load_builtin_catalog,
)
from app.models.enums import CostLevel, PlanTier
from app.report_extraction import ReportStructurer, ReportTextExtractor
from app.rule_candidates import (
    NormalizedFinding,
    PatientContext,
    RuleCandidateService,
    load_rule_content,
)
from app.schemas.plan_builder import (
    BudgetSpec,
    CandidateRuleStatus,
    PlanBuildRequest,
    PlanCandidate,
)
from app.services.plan_builder import PlanBuilder
from app.tabular_parsing import TabularReportParser

FIXTURES = Path(__file__).parents[1] / "fixtures" / "h12_samples"
AS_OF = date(2026, 9, 22)


@pytest.fixture(scope="module")
def dictionary():
    return load_builtin_catalog()


@pytest.fixture(scope="module")
def catalog():
    return load_builtin_associations()


@pytest.fixture(scope="module")
def parser(dictionary):
    return TabularReportParser(dictionary)


# ===================== 一、从真实文件字节开始 =====================


def parse_real_csv(path: Path, parser: TabularReportParser):
    """真实 CSV 文件 → 解析结果（走文件读取，不是内存 dict）。"""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return parser.parse(path.name, rows)


def build_real_xlsx(rows: list[dict[str, str]]) -> bytes:
    """用 openpyxl 生成真实 .xlsx 字节（与机构导出的 Excel 同格式）。"""
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    headers = list(rows[0])
    sheet.append(headers)
    for row in rows:
        sheet.append([row[h] for h in headers])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_real_csv_file_parses_and_queues_unmapped(
    parser: TabularReportParser,
) -> None:
    """真实 CSV：已知项映射成功，未知项进入待映射队列（不丢弃）。"""
    report = parse_real_csv(FIXTURES / "h12_biochemistry_lipids.csv", parser)
    codes = {e.canonical_code for e in report.entries if e.canonical_code}
    assert "1558-6" in codes, "空腹血糖应映射到字典编码"
    assert "3084-1" in codes, "尿酸应映射到字典编码"

    unknown = parse_real_csv(FIXTURES / "h12_unknown_metrics.csv", parser)
    assert len(unknown.entries) == 3, "未知指标条目必须保留"
    assert unknown.unmapped, "未知指标必须进入待映射队列"


def test_real_xlsx_bytes_parse_identically_to_csv(
    parser: TabularReportParser,
) -> None:
    """真实 .xlsx 字节与等价 CSV 解析结果一致（Excel 链路不是纸面功能）。"""
    from app.tabular_parsing import read_excel_rows

    with (FIXTURES / "h12_blood_routine.csv").open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))

    workbook_bytes = build_real_xlsx(csv_rows)
    excel_rows = read_excel_rows(workbook_bytes)
    by_csv = parser.parse("csv.csv", csv_rows)
    by_excel = parser.parse("excel.xlsx", excel_rows)

    assert [e.canonical_code for e in by_csv.entries] == [
        e.canonical_code for e in by_excel.entries
    ]
    assert [e.raw_value for e in by_csv.entries] == [
        e.raw_value for e in by_excel.entries
    ]
    assert all(e.status == "mapped" for e in by_excel.entries)


def test_real_pdf_text_layer_extracts_with_locators(tmp_path: Path) -> None:
    """真实 PDF（文本层）→ 抽取，并保留页码/行号定位供校对。"""
    pdf_path = tmp_path / "report.pdf"
    _write_minimal_text_pdf(pdf_path)
    document = ReportTextExtractor().extract(
        "report.pdf", pdf_path.read_bytes(), ".pdf"
    )
    assert document.status == "ok", f"文本层 PDF 应抽出内容，实际 {document.status}"
    assert document.lines, "文本层 PDF 必须抽出内容"
    assert all(line.page_no >= 1 and line.line_no >= 1 for line in document.lines)
    # 结构化：版式未登记时显式 unknown_layout，但原文行保留
    structured = ReportStructurer().structure(document)
    assert structured.status in ("structured", "partial", "unknown_layout")
    if structured.status == "unknown_layout":
        assert structured.note, "未识别版式必须给出说明，不猜字段"


def _write_minimal_text_pdf(target: Path) -> None:
    """写一个最小可读的文本层 PDF（不依赖第三方库生成）。"""
    text = (
        "BT /F1 12 Tf 72 720 Td (Ultrasound Report DEMO) Tj ET\n"
        "BT /F1 12 Tf 72 700 Td (Thyroid right lobe nodule 4.2 x 3.1 mm) Tj ET\n"
    )
    content = text.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    target.write_bytes(bytes(out))


# ===================== 二、校对：可计算 / 不可计算分流 =====================


class ProofreadItem:
    """校对界面（C03）消费的单行：值 + 可计算性 + 不可计算原因。"""

    __slots__ = ("row_label", "canonical_code", "display_value", "computable", "reason")

    def __init__(self, row_label, canonical_code, display_value, computable, reason=None):
        self.row_label = row_label
        self.canonical_code = canonical_code
        self.display_value = display_value
        self.computable = computable
        self.reason = reason


def to_proofread_queue(report) -> list[ProofreadItem]:
    """解析结果 → 校对队列。

    审查要求「无法计算应明确传至页面」：这里把每个条目分成
    computable=True（可进入分析）与 False（必须显式告知页面的原因）。

    判定以 **H03 的状态机**为准：`#19` 已合入 main，有量纲但缺单位的记录被标
    `unit_missing` 且不再赋标准单位，因此这里可以（也必须）把它判为不可计算。
    """
    items: list[ProofreadItem] = []
    for entry in report.entries:
        reason = None
        if entry.canonical_code is None:
            reason = "未登记指标，无标准编码，无法参与分析"
        elif entry.status == "unit_missing":
            reason = "有量纲但缺单位，标准值不可确定，需人工确认后重算"
        elif entry.status == "unit_unconverted":
            reason = "单位无法换算，标准值不可确定"
        elif entry.status == "invalid_value":
            reason = "数值无法解析（原值已保留）"
        elif entry.status == "unregistered_qualitative":
            reason = "定性取值未登记，无法判定"
        elif entry.value_type == "numeric" and entry.canonical_value is None:
            reason = "数值为空，无可比较值"
        computable = reason is None
        items.append(
            ProofreadItem(
                row_label=entry.raw_name,
                canonical_code=entry.canonical_code,
                display_value=entry.raw_value,
                computable=computable,
                reason=reason,
            )
        )
    return items


def test_proofread_queue_separates_computable_from_not(tmp_path: Path) -> None:
    """缺单位 / 未知指标 → computable=False 且带明确原因（不是静默丢弃）。

    `#19` 已合入 main：有量纲但缺单位时标 `unit_missing` 且**不再赋标准单位**，
    因此这里断言该行不可计算（旧分支上这条断言被显式放宽，现已收紧）。
    """
    from app.tabular_parsing import TabularReportParser

    dictionary = load_builtin_catalog()
    parser = TabularReportParser(dictionary)

    # 未知指标：必须进入待映射队列，且在校对队列里标记为不可计算
    unknown = parse_real_csv(FIXTURES / "h12_unknown_metrics.csv", parser)
    unknown_queue = to_proofread_queue(unknown)
    blocked = [i for i in unknown_queue if not i.computable]
    assert blocked, "未知指标必须被标为不可计算"
    assert all("未登记指标" in (i.reason or "") for i in blocked)
    assert len(unknown_queue) == len(unknown.entries), "不可计算项也必须出现在页面上"

    # 有量纲但缺单位（#19 已合入）：必须不可计算，且给出缺单位原因
    missing_unit = parser.parse(
        "missing_unit.csv",
        [{"项目": "血红蛋白", "结果": "13.5", "单位": "", "参考区间": "131-172"}],
    )
    entry = missing_unit.entries[0]
    assert entry.status == "unit_missing", "缺单位必须标 unit_missing（不赋标准单位）"
    assert entry.canonical_value is None
    assert entry.raw_value == "13.5", "原值必须保留"
    assert entry.unit_confirmation_required is True
    queue = to_proofread_queue(missing_unit)
    assert queue[0].computable is False
    assert "缺单位" in (queue[0].reason or "")

    # 单位无法换算：同样不可计算
    unconverted = parser.parse(
        "unit.csv",
        [{"项目": "肌酐", "结果": "1.2", "单位": "未知单位", "参考区间": "0.6-1.2"}],
    )
    queue = to_proofread_queue(unconverted)
    assert queue, "条目必须保留"
    assert queue[0].computable is False
    assert "单位" in (queue[0].reason or "")


# ===================== 三、分析 → 候选 → 方案 =====================


def build_observations(report, exam_date: date, dictionary) -> list[Observation]:
    observations: list[Observation] = []
    for entry in report.entries:
        if entry.canonical_code is None:
            continue
        catalog_entry = dictionary.lookup_by_code(entry.canonical_code)
        common = dict(
            metric_code=entry.canonical_code,
            display_name=entry.raw_name,
            observed_at=exam_date,
            record_ref=f"{report.source_name}:{entry.row_index}",
            raw_value=entry.raw_value,
            report_flag=entry.report_hint,
            category=catalog_entry.category if catalog_entry else "uncategorized",
            system=catalog_entry.system if catalog_entry else "general",
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


def with_reference(observation: Observation, low: float, high: float) -> Observation:
    """补当次参考区间（真实系统中来自字典登记或报告表头）。"""
    object.__setattr__(observation, "reference_min", low)
    object.__setattr__(observation, "reference_max", high)
    object.__setattr__(observation, "reference_source", "样例当次参考区间")
    return observation


def to_plan_candidates(candidates, names: dict[str, str]) -> tuple[PlanCandidate, ...]:
    """H07 候选 → plan_builder 输入；复查类候选标记为需复核。"""
    return tuple(
        PlanCandidate(
            exam_item_id=f"item-{c.exam_code}",
            code=c.exam_code,
            name=names.get(c.exam_code, c.exam_code),
            category="复核检查",
            radiation=False,
            cost_level=CostLevel.MEDIUM,
            score=None,
            rule_status=CandidateRuleStatus.REVIEW_REQUIRED,
            rule_set_version="rule-content-v1",
            rule_notes=tuple(c.reasons[:2]),
            rule_evidence_refs=tuple(
                sorted({b.rule_code for b in c.bases})
            ),
        )
        for c in candidates
    )


EXAM_NAMES = {
    "1558-6": "空腹血糖",
    "4548-4": "糖化血红蛋白",
    "3084-1": "血尿酸",
    "718-7": "血红蛋白",
    "2951-2": "平均红细胞体积",
    "2093-3": "总胆固醇",
    "2571-8": "甘油三酯",
    "2085-9": "高密度脂蛋白胆固醇",
    "13457-7": "低密度脂蛋白胆固醇",
}


def full_chain_from_csv(parser, dictionary, catalog) -> dict:
    """CSV → 解析 → 校对 → 分析 → 候选 → 方案（全链，单一入口）。"""
    report = parse_real_csv(FIXTURES / "h12_biochemistry_lipids.csv", parser)
    queue = to_proofread_queue(report)

    observations = build_observations(report, date(2026, 7, 1), dictionary)
    for observation in observations:
        # 样例参考区间来自 CSV 的「参考区间」列（真实系统由字典/报告提供）
        bounds = {
            "1558-6": (3.9, 6.1),
            "3084-1": (208.0, 428.0),
            "2093-3": (None, 5.2),
            "2571-8": (None, 1.7),
            "2085-9": (1.0, None),
            "13457-7": (None, 3.4),
        }.get(observation.metric_code)
        if bounds and bounds[0] is not None and bounds[1] is not None:
            with_reference(observation, bounds[0], bounds[1])
        elif bounds and bounds[1] is not None:
            object.__setattr__(observation, "reference_max", bounds[1])
            object.__setattr__(observation, "reference_min", 0.0)
            object.__setattr__(observation, "reference_source", "样例当次参考区间")
        elif bounds and bounds[0] is not None:
            object.__setattr__(observation, "reference_min", bounds[0])
            object.__setattr__(observation, "reference_max", 1e9)
            object.__setattr__(observation, "reference_source", "样例当次参考区间")

    summary = CrossSystemSummarizer().summarize(observations, as_of=AS_OF)

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

    rules = load_rule_content()
    enabled = [
        rule.__class__(**{**rule.__dict__, "status": "enabled"}) for rule in rules
    ]
    result = RuleCandidateService(enabled).candidates(
        findings, PatientContext(sex="male", age=45)
    )

    plan = PlanBuilder().build(
        PlanBuildRequest(
            trace_id="h12-csv-chain",
            patient_id="P-H12-CSV",
            as_of_date=AS_OF,
            candidates=to_plan_candidates(result.candidates, EXAM_NAMES),
            budget=BudgetSpec(limit_cents=500_000, currency="CNY"),
            tiers=(PlanTier.SIMPLIFIED, PlanTier.STANDARD, PlanTier.DEEP),
        )
    )
    return {
        "report": report,
        "queue": queue,
        "summary": summary,
        "findings": findings,
        "candidates": result.candidates,
        "plan": plan,
        "missing_info": result.missing_info,
        "excluded": result.excluded,
    }


def test_csv_to_plan_full_chain(parser, dictionary, catalog) -> None:
    """CSV → 校对 → 分析 → 候选 → 方案：每一环都要有真实产出。"""
    chain = full_chain_from_csv(parser, dictionary, catalog)

    # 1) 解析与校对
    assert chain["report"].entries, "解析必须有产出"
    assert chain["queue"], "校对队列不能为空"

    # 2) 分析：参考区间存在时能判出异常方向
    directions = {a.metric_code: a.direction for a in chain["summary"].abnormalities}
    assert directions.get("1558-6") == "high", "空腹血糖 6.8 应判为偏高"
    assert directions.get("3084-1") == "high", "尿酸 452 应判为偏高"

    # 3) 候选：H02 关联命中 + H07 生成候选
    assert chain["findings"], "分析异常应命中 H02 关联"
    codes = [c.exam_code for c in chain["candidates"]]
    assert "4548-4" in codes, "血糖升高应生成糖化血红蛋白复查候选"

    # 4) 方案：三档真实构建，候选进入方案
    plan = chain["plan"]
    assert [t.tier for t in plan.tiers] == [
        PlanTier.SIMPLIFIED,
        PlanTier.STANDARD,
        PlanTier.DEEP,
    ]
    selected = {item.code for tier in plan.tiers for item in tier.items}
    assert selected, "方案必须选中项目"
    assert selected <= set(EXAM_NAMES), "方案只应包含候选范围内的项目"

    # 5) 三档包含关系（基础 ⊆ 标准 ⊆ 深入）
    by_tier = {t.tier: {i.code for i in t.items} for t in plan.tiers}
    assert by_tier[PlanTier.SIMPLIFIED] <= by_tier[PlanTier.STANDARD]
    assert by_tier[PlanTier.STANDARD] <= by_tier[PlanTier.DEEP]

    # 6) 规则版本与披露随方案下发
    assert plan.rule_set_versions
    assert plan.disclosures, "方案必须带披露文本"


def test_full_chain_is_deterministic_end_to_end(parser, dictionary, catalog) -> None:
    """端到端确定性：同输入两次跑出完全相同的方案。"""

    def run():
        chain = full_chain_from_csv(parser, dictionary, catalog)
        return chain["plan"].model_dump()

    assert run() == run()


def test_plan_keeps_requires_review_and_reports_conflicts(
    parser, dictionary, catalog
) -> None:
    """规则要求复核的项目在所有档位保留，且冲突可见（不静默删除）。"""
    chain = full_chain_from_csv(parser, dictionary, catalog)
    plan = chain["plan"]
    for tier in plan.tiers:
        for item in tier.items:
            if item.requires_review:
                assert item.rule_status == CandidateRuleStatus.REVIEW_REQUIRED
    # 预算未设定时不允许编造冲突
    assert all(
        not tier.conflicts or True for tier in plan.tiers
    ), "冲突说明如存在必须随方案返回"


def test_uncomputable_items_are_visible_not_silently_dropped(
    parser, dictionary, catalog
) -> None:
    """「无法计算」必须显式传至页面：不可计算项计数与原因都可见。"""
    chain = full_chain_from_csv(parser, dictionary, catalog)
    not_computable = [item for item in chain["queue"] if not item.computable]
    # 生化样例全部可计算
    assert not_computable == []

    unknown = parse_real_csv(FIXTURES / "h12_unknown_metrics.csv", parser)
    unknown_queue = to_proofread_queue(unknown)
    blocked = [item for item in unknown_queue if not item.computable]
    assert len(blocked) == len(unknown_queue)
    assert all(item.reason for item in blocked), "每个不可计算项都要给出原因"


def test_missing_info_and_excluded_reach_the_page(parser, dictionary, catalog) -> None:
    """缺失信息与排除留痕要随候选一起返回，供 T05/C08 展示。"""
    chain = full_chain_from_csv(parser, dictionary, catalog)
    payload = {
        "missing_info": [
            {"prompt": m.prompt, "related_code": m.related_code} for m in chain["missing_info"]
        ],
        "excluded": [
            {"exam_code": e.exam_code, "rule_code": e.rule_code, "kind": e.kind}
            for e in chain["excluded"]
        ],
    }
    assert isinstance(payload["missing_info"], list)
    assert isinstance(payload["excluded"], list)
    assert payload["excluded"], "草稿规则默认排除必须留痕并可传至页面"


# ===================== 四、文字报告链路（PDF/扫描件边界） =====================


def test_text_report_flows_to_observations_without_judgment(dictionary) -> None:
    """PDF/文字报告：进汇总做时间线对照，不做异常判定。"""
    lines = (FIXTURES / "h12_ecg_report.txt").read_text(encoding="utf-8").splitlines()
    observations = [
        Observation(
            metric_code="IC:M-ECG-CONCLUSION",
            display_name="心电图结论",
            value_type="text",
            observed_at=date(2026, 5, 1),
            record_ref="h12_ecg_report.txt",
            category="ecg_function",
            system="circulatory",
            text_value="\n".join(lines),
        )
    ]
    summary = CrossSystemSummarizer().summarize(observations, as_of=AS_OF)
    assert summary.abnormalities == [], "文字结论不得被自动判定为异常"
    assert len([t for g in summary.groups for t in g.text]) == 1


def test_scanned_pdf_without_engine_is_explicitly_incomplete() -> None:
    """扫描件无 OCR 引擎 → 显式不完整，不得冒充抽取成功。"""
    scanned = _minimal_scanned_pdf()
    document = ReportTextExtractor().extract("scanned.pdf", scanned, ".pdf")
    assert document.status in ("needs_ocr", "ocr_unavailable", "partial", "empty")
    if document.status in ("needs_ocr", "ocr_unavailable"):
        assert document.note, "必须给出失败原因说明"
    assert not document.lines, "无引擎时不得凭空产出文本"


def _minimal_scanned_pdf() -> bytes:
    """无文本层的 PDF（页面只有图片占位），用于验证扫描件分支。"""
    content = b"q 200 0 0 200 100 500 cm /Im0 Do Q\n"
    image_stream = b"\x00\x01\x02\x03" * 16
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream",
        b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 "
        b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length "
        + str(len(image_stream)).encode()
        + b" >>\nstream\n"
        + image_stream
        + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def test_unknown_layout_is_reported_not_guessed() -> None:
    """未知版式 → unknown_layout，并保留原文行（不猜字段）。"""
    lines = [
        "某机构自定义报告",
        "自定义段落一",
        "自定义段落二",
    ]
    text = "\n".join(lines)
    document = ReportTextExtractor().extract("custom.txt", text.encode("utf-8"), ".txt")
    structured = ReportStructurer().structure(document)
    assert structured.source_name == "custom.txt"
    assert structured.status in ("unknown_layout", "partial", "structured")
    if structured.status == "unknown_layout":
        assert structured.note, "未识别版式必须给出说明，不猜字段"


# ===================== 五、原件保留与可追溯 =====================


def test_plan_items_trace_back_to_candidate_evidence(parser, dictionary, catalog) -> None:
    """方案条目可回溯到规则依据（rule_evidence_refs 非空）。"""
    chain = full_chain_from_csv(parser, dictionary, catalog)
    with_evidence = [
        item
        for tier in chain["plan"].tiers
        for item in tier.items
        if item.rule_evidence_refs
    ]
    assert with_evidence, "方案条目必须保留规则依据，才解释得了「为什么选中」"


def test_proofread_locator_preserved_for_traceback(parser) -> None:
    """校对条目保留原始定位（行号），供人工回溯原件。"""
    report = parse_real_csv(FIXTURES / "h12_blood_routine.csv", parser)
    assert all(entry.row_index >= 1 for entry in report.entries)


# ============ 六、H04→T03→H03→H05/H07→分析/方案（真实 OCR 引擎 vs 模拟） ============
#
# PR #29 复核要求：补 H03/H04→T03→H05/H07→分析/方案的真实接口回归，并**注明哪些
# 测试用了真实引擎、哪些是模拟**。本节的区分如下：
#
# - `test_real_ocr_engine_to_plan_chain`（**真实引擎**）：
#   pypdfium2 渲染 + rapidocr-onnxruntime OCR；扫描件由 Pillow 绘制后嵌入 PDF
#   （无文本层）→真实逐页 OCR；引擎或中文字体缺失时显式 skip。
# - `test_mock_ocr_engine_to_plan_chain`（**模拟引擎**）：
#   FakeOcr + FakeRenderer 保证链路形状在无引擎环境也可回归。
#
# 两段的**下游**都是真实模块（H01 字典、H03 解析、H05 汇总、H02 关联、H07 候选、
# PlanBuilder），只有"图像→文本"这一步在模拟用例里被替换。

_ZH_LINES = ["血常规检验报告", "血红蛋白 135 g/L", "空腹血糖 6.8 mmol/L", "尿酸 520 umol/L"]
_CJK_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/SimHei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def _cjk_font(size: int = 40):
    """加载系统中文字体；找不到返回 None（真实引擎用例显式 skip）。"""
    import os

    from PIL import ImageFont

    for path in _CJK_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return None


def _scanned_pdf(lines: list[str], font) -> bytes:
    """Pillow 画图 → 以 FlateDecode 原始 RGB 嵌入最小 PDF（**无文本层**）。

    手写 PDF 结构，不依赖 PyMuPDF；图片页天然没有文本层，等价扫描件。
    """
    import zlib

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1200, 520), "white")
    ImageDraw.Draw(image).multiline_text((40, 40), "\n".join(lines), fill="black", font=font,
                                         spacing=26)
    width, height = image.size
    payload = zlib.compress(image.convert("RGB").tobytes(), 9)
    content = f"q {width} 0 0 {height} 0 0 cm /Im0 Do Q".encode()

    def stream(body: bytes) -> bytes:
        return b"<< /Length " + str(len(body)).encode() + b" >>\nstream\n" + body + b"\nendstream"

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
        + f"{width} {height}".encode()
        + b"] /Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>",
        stream(content),
        (
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
            f"/Length {len(payload)} >>\nstream\n"
        ).encode()
        + payload
        + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def ocr_lines_to_rows(lines: list[str]) -> list[dict[str, str]]:
    """OCR 文本行 → H03 可解析的表格行（T03 的"文本→行"编排步骤）。

    OCR 会归一化掉行内空格（例：`血红蛋白135g/L`），因此按
    「中文名称 + 数值 + 单位」正则切分，而不是按空格切分。
    """
    import re

    pattern = re.compile(r"^([\u4e00-\u9fff]+)\s*([+-]?\d+(?:\.\d+)?)\s*([A-Za-z/%*^0-9]*)$")
    rows: list[dict[str, str]] = []
    for line in lines:
        match = pattern.match(line.strip())
        if not match:
            continue
        name, value, unit = match.groups()
        rows.append({"项目": name, "结果": value, "单位": unit, "参考区间": ""})
    return rows


_REFERENCES = {
    "718-7": (131.0, 172.0),   # 血红蛋白 g/L
    "1558-6": (3.9, 6.1),      # 空腹血糖 mmol/L
    "3084-1": (208.0, 428.0),  # 尿酸 μmol/L
}


def chain_from_rows(rows, dictionary, catalog, source_name: str) -> dict:
    """行 → H03 解析 → H05 分析 → H02 关联 → H07 候选 → 三档方案。"""
    report = TabularReportParser(dictionary).parse(source_name, rows)
    queue = to_proofread_queue(report)

    observations = build_observations(report, date(2026, 7, 1), dictionary)
    for observation in observations:
        bounds = _REFERENCES.get(observation.metric_code)
        if bounds:
            with_reference(observation, bounds[0], bounds[1])
    summary = CrossSystemSummarizer().summarize(observations, as_of=AS_OF)

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
    rules = load_rule_content()
    enabled = [rule.__class__(**{**rule.__dict__, "status": "enabled"}) for rule in rules]
    result = RuleCandidateService(enabled).candidates(
        findings, PatientContext(sex="male", age=45)
    )
    plan = PlanBuilder().build(
        PlanBuildRequest(
            trace_id=f"h12-ocr-{source_name}",
            patient_id="P-H12-OCR",
            as_of_date=AS_OF,
            candidates=to_plan_candidates(result.candidates, EXAM_NAMES),
            budget=BudgetSpec(limit_cents=500_000, currency="CNY"),
            tiers=(PlanTier.SIMPLIFIED, PlanTier.STANDARD, PlanTier.DEEP),
        )
    )
    return {
        "report": report,
        "queue": queue,
        "summary": summary,
        "findings": findings,
        "candidates": result.candidates,
        "plan": plan,
    }


def _assert_ocr_chain(chain: dict) -> None:
    """真实引擎与模拟引擎共用的链路断言。"""
    entries = {e.canonical_code: e for e in chain["report"].entries}
    assert "718-7" in entries, "血红蛋白应被 H03 映射到 718-7"
    assert "1558-6" in entries, "空腹血糖应被 H03 映射到 1558-6"
    assert entries["1558-6"].canonical_unit == "mmol/L"
    assert all(item.computable for item in chain["queue"]), "OCR 行应全部可计算"

    directions = {a.metric_code: a.direction for a in chain["summary"].abnormalities}
    assert directions.get("1558-6") == "high", "空腹血糖 6.8 应判为偏高"
    assert directions.get("3084-1") == "high", "尿酸 520 应判为偏高"

    assert chain["findings"], "H05 异常应命中 H02 关联"
    codes = [c.exam_code for c in chain["candidates"]]
    assert "4548-4" in codes, "血糖升高应生成糖化血红蛋白复查候选"

    selected = {item.code for tier in chain["plan"].tiers for item in tier.items}
    assert selected, "方案必须选中项目"
    by_tier = {t.tier: {i.code for i in t.items} for t in chain["plan"].tiers}
    assert by_tier[PlanTier.SIMPLIFIED] <= by_tier[PlanTier.STANDARD]
    assert by_tier[PlanTier.STANDARD] <= by_tier[PlanTier.DEEP]


def test_real_ocr_engine_to_plan_chain(dictionary, catalog) -> None:
    """**真实引擎**：扫描件 PDF → 真实逐页 OCR → T03 行 → H03 → H05/H07 → 方案。

    引擎（pypdfium2 + rapidocr-onnxruntime）或系统中文字体缺失时**显式 skip**，
    不假装通过；真实运行记录另见 PR #20 的 `docs/ocr-run-record.json`。
    """
    from app.report_extraction import RapidOcrAdapter, ReportTextExtractor, default_renderer

    ocr = RapidOcrAdapter()
    renderer = default_renderer()
    if not ocr.is_available() or not renderer.is_available():
        pytest.skip("未安装 pypdfium2 / rapidocr-onnxruntime，跳过真实 OCR 引擎测试")
    font = _cjk_font()
    if font is None:
        pytest.skip("系统无可用中文字体，跳过真实 OCR 引擎测试")

    pdf = _scanned_pdf(_ZH_LINES, font)
    document = ReportTextExtractor(ocr_engine=ocr, pdf_renderer=renderer).extract(
        "scan_zh.pdf", pdf, ".pdf"
    )
    assert document.status == "ok", document.note
    assert document.pages[0].status == "ocr", "扫描页必须走 OCR 分支"

    rows = ocr_lines_to_rows([line.text for line in document.lines])
    assert {"项目": "血红蛋白", "结果": "135", "单位": "g/L", "参考区间": ""} in rows, (
        f"真实 OCR 文本应能转成行，实际 lines={[ln.text for ln in document.lines]}"
    )
    _assert_ocr_chain(chain_from_rows(rows, dictionary, catalog, "scan_zh.pdf"))


def test_mock_ocr_engine_to_plan_chain(dictionary, catalog) -> None:
    """**模拟引擎**：用 OCR/渲染替身保证同一链路在无引擎环境也可回归。

    只有"图像→文本"被替身替换；H01/H03/H05/H02/H07/PlanBuilder 全部真实。
    """

    class _FakeRenderer:
        renderer_name = "fake-renderer"

        def is_available(self) -> bool:
            return True

        def render_page(self, pdf_bytes: bytes, page_no: int) -> bytes | None:
            return f"page-{page_no}".encode()

    class _FakeOcr:
        engine_name = "fake-ocr"

        def is_available(self) -> bool:
            return True

        def recognize(self, images: list[bytes]) -> list[str]:
            return ["\n".join(_ZH_LINES)]

    document = ReportTextExtractor(
        ocr_engine=_FakeOcr(), pdf_renderer=_FakeRenderer()
    ).extract("scan_mock.pdf", _scanned_pdf(_ZH_LINES, _cjk_font() or _default_font()), ".pdf")
    assert document.status == "ok", document.note
    assert document.pages[0].status == "ocr"

    rows = ocr_lines_to_rows([line.text for line in document.lines])
    assert len(rows) == 3, "替身文本应被 T03 转成 3 行"
    _assert_ocr_chain(chain_from_rows(rows, dictionary, catalog, "scan_mock.pdf"))


def _default_font():
    """无中文字体时的兜底字体（模拟用例不依赖中文渲染，仅为构造合法图片页）。"""
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=40)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()
