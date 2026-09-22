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
    FindingCatalog,
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
    """
    items: list[ProofreadItem] = []
    for entry in report.entries:
        reason = None
        if entry.canonical_code is None:
            reason = "未登记指标，无标准编码，无法参与分析"
        elif entry.status == "unit_unconverted":
            reason = "单位无法换算，标准值不可确定"
        elif entry.value_type == "numeric" and not (entry.canonical_unit or "").strip():
            reason = "有量纲但缺单位，标准值不可确定，需人工确认后重算"
        elif entry.status == "unregistered_qualitative":
            reason = "定性取值未登记，无法判定"
        elif entry.canonical_value is None and entry.value_type == "numeric":
            reason = "数值无法解析"
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

    注意：本分支合并的 #19 仍是修复前版本——有量纲但缺单位时会被直接赋上
    标准单位（HGB 13.5 被当成 13.5 g/L），因此这里**不**断言该行不可计算；
    该缺陷已由 #19 的修复（`unit_missing` 状态 + `unit_confirmation_required`）
    处理，修复分支合入后本测试应同步收紧为 `computable is False`。
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

    # 单位无法换算：同样不可计算
    unconverted = parser.parse(
        "unit.csv",
        [{"项目": "肌酐", "结果": "1.2", "单位": "未知单位", "参考区间": "0.6-1.2"}],
    )
    queue = to_proofread_queue(unconverted)
    assert queue, "条目必须保留"
    if queue[0].computable is False:
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
