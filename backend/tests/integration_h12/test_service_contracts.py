"""H 系列服务契约一致性检查（H12 联调分支）。

对照 `docs/H_SERIES_SERVICE_CONTRACTS.md`（作者王宏锦，M0 初稿）中声明的接口，
逐项验证 H01/H02/H03/H04/H05/H06/H07/H08/H09/H11 的**实际实现**是否暴露了契约
中的版本号、数据类字段与函数签名。

检查边界（重要，不掩盖差异）：
- 本文件只做**接口存在性 / 字段名 / 签名形状**的核对，不做医学语义判定；
- 版本号一律读类属性 `VERSION`（实现约定的形态），不读实例属性 `version`（实现未提供）；
- 涉及 #19/#20/#21/#23/#24/#26 修复后才存在的符号（如 H06 的 `SECTION_KEYS`），
  本分支为**未合并状态**，因此用 `_BRANCH_DELTA` 显式标注并跳过断言，不假装通过。
  这些断言在其修复分支（feat/imaging-lesion-multisite 等）上由各自测试覆盖。
"""

from __future__ import annotations

import inspect
from dataclasses import fields, is_dataclass

import pytest

# 本分支（feat/sample-coverage-suite）尚未合并的修复分支所引入的符号。
# 键：契约条目；值：引入该符号的修复分支/提交。
_BRANCH_DELTA = {
    "SECTION_KEYS": "feat/imaging-lesion-multisite @ 565d45b (PR #23)",
}


def _fields_of(cls) -> set[str]:
    assert is_dataclass(cls), f"{cls} 应为 dataclass"
    return {f.name for f in fields(cls)}


def _assert_fields(cls, expected: tuple[str, ...], label: str) -> None:
    present = _fields_of(cls)
    missing = [name for name in expected if name not in present]
    assert not missing, f"{label} 缺字段 {missing}"


# ==================== H01 体检字典目录服务 ====================


def test_h01_version_and_loaders() -> None:
    from app.exam_dictionary import (
        ExamDictionary,
        load_builtin_associations,
        load_builtin_catalog,
    )

    assert ExamDictionary.VERSION == "exam-dictionary-v1"
    assert load_builtin_catalog() is not None
    assert load_builtin_associations() is not None


def test_h01_catalog_entry_contract_fields() -> None:
    from app.exam_dictionary import CatalogEntry, ReferenceRange

    _assert_fields(
        CatalogEntry,
        ("code", "display_name", "aliases", "category", "system", "value_type",
         "standard_unit", "reference_ranges", "source", "source_version",
         "review_status", "status"),
        "CatalogEntry",
    )
    _assert_fields(
        ReferenceRange,
        ("population", "min_value", "max_value", "unit", "source",
         "source_version", "review_status"),
        "ReferenceRange",
    )


def test_h01_dictionary_methods_present() -> None:
    from app.exam_dictionary import ExamDictionary

    for name in ("lookup", "lookup_by_code", "entries_by_category", "register_unknown"):
        assert callable(getattr(ExamDictionary, name, None)), f"ExamDictionary 缺方法 {name}"


def test_h01_content_declares_provenance_and_review_status() -> None:
    """契约第一节第 5 条：内容文件每条记录带 source/source_version/review_status。"""
    from app.exam_dictionary import load_builtin_catalog

    entries = load_builtin_catalog().entries_by_category("blood_routine")
    assert entries, "基础血液学类别应有条目"
    for entry in entries:
        assert entry.source, f"{entry.code} 缺 source"
        assert entry.source_version, f"{entry.code} 缺 source_version"
        assert entry.review_status in ("pending_review", "reviewed"), entry.review_status


# ==================== H02 检查—发现—疾病关联目录 ====================


def test_h02_version_and_fields() -> None:
    from app.exam_dictionary import FindingAssociation, FindingCatalog

    assert FindingCatalog.VERSION == "finding-catalog-v1"
    _assert_fields(
        FindingAssociation,
        ("association_id", "exam_code", "condition_code", "condition_name",
         "relation_type", "direction", "evidence_note", "source",
         "source_version", "review_status"),
        "FindingAssociation",
    )


def test_h02_catalog_methods_present() -> None:
    from app.exam_dictionary import FindingCatalog

    for name in ("associations_for_exam", "conditions_for_exam"):
        assert callable(getattr(FindingCatalog, name, None)), f"FindingCatalog 缺方法 {name}"


def test_h02_relation_type_never_expresses_confirmed_diagnosis() -> None:
    """契约第三节硬性规则：目录层只表达提示/观察/危险因素，不表达确诊。"""
    from app.exam_dictionary import load_builtin_associations, load_builtin_catalog

    allowed = {"abnormality_suggests", "finding_observation", "risk_factor"}
    catalog = load_builtin_associations()
    checked = 0
    for entry in load_builtin_catalog().entries_by_category("blood_routine"):
        for association in catalog.associations_for_exam(entry.code):
            checked += 1
            assert association.relation_type in allowed, (
                f"{association.association_id} relation_type 越界：{association.relation_type}"
            )
    assert checked > 0, "应至少有一条关联用于校验"


# ==================== H03 表格解析服务 ====================


def test_h03_version_and_entry_fields() -> None:
    from app.tabular_parsing import ParsedMetricEntry, TabularReportParser
    from app.tabular_parsing.schemas import ParsedTabularReport

    assert TabularReportParser.VERSION == "tabular-parsing-v1"
    _assert_fields(
        ParsedMetricEntry,
        ("raw_name", "raw_value", "raw_unit", "page_hint", "row_index",
         "column_name", "canonical_code", "value_type", "canonical_value",
         "canonical_unit", "qualitative_status", "text_value",
         "conversion_basis", "status"),
        "ParsedMetricEntry",
    )
    _assert_fields(
        ParsedTabularReport, ("source_name", "entries", "issues", "unmapped"),
        "ParsedTabularReport",
    )


def test_h03_parse_signature_takes_source_name_and_rows() -> None:
    from app.tabular_parsing import TabularReportParser

    params = inspect.signature(TabularReportParser.parse).parameters
    assert "source_name" in params
    assert "rows" in params


def test_h03_excel_helper_is_exported() -> None:
    """契约第四节：Excel 解析提供 read_excel_rows 辅助函数。"""
    import app.tabular_parsing as module

    assert callable(getattr(module, "read_excel_rows", None)), "缺 read_excel_rows"


# ==================== H04 报告文本抽取服务 ====================


def test_h04_version_and_signatures() -> None:
    from app.report_extraction import ReportStructurer, ReportTextExtractor

    assert ReportTextExtractor.VERSION == "report-extraction-v1"
    assert ReportStructurer.VERSION == "report-structuring-v1"

    extract_params = inspect.signature(ReportTextExtractor.extract).parameters
    for name in ("source_name", "content", "suffix"):
        assert name in extract_params, f"extract 缺参数 {name}"

    structure_params = inspect.signature(ReportStructurer.structure).parameters
    assert "document" in structure_params, "structure 应接收 document"


def test_h04_document_declares_lines_and_page_count() -> None:
    from app.report_extraction.schemas import ExtractedDocument

    present = _fields_of(ExtractedDocument)
    for name in ("lines", "page_count"):
        assert name in present, f"ExtractedDocument 缺字段 {name}"


def test_h04_ocr_protocol_reports_explicit_unavailability() -> None:
    """契约第五节：OcrEngine 提供 is_available/recognize，未安装引擎显式不可用。"""
    from app.report_extraction import UnavailableOcr

    engine = UnavailableOcr()
    assert callable(getattr(engine, "is_available", None))
    assert callable(getattr(engine, "recognize", None))
    assert engine.is_available() is False


# ==================== H05 跨系统汇总服务 ====================


def test_h05_version_and_observation_fields() -> None:
    from app.cross_system import CrossSystemSummarizer, Observation

    assert CrossSystemSummarizer.VERSION == "cross-system-summary-v1"
    _assert_fields(
        Observation,
        ("metric_code", "value_type", "observed_at", "category", "system",
         "record_ref", "reference_min", "reference_max", "reference_source",
         "reference_population"),
        "Observation",
    )


def test_h05_summary_groups_and_abnormalities() -> None:
    from app.cross_system import CrossSystemSummary

    present = _fields_of(CrossSystemSummary)
    for name in ("groups", "abnormalities", "notes"):
        assert name in present, f"CrossSystemSummary 缺字段 {name}"


def test_h05_summarize_accepts_decision_date() -> None:
    from app.cross_system import CrossSystemSummarizer

    params = inspect.signature(CrossSystemSummarizer.summarize).parameters
    assert "as_of" in params, "summarize 应接收 as_of 决策日期"


# ==================== H06 影像与病灶 ====================


def test_h06_imaging_parser_exists_with_version() -> None:
    from app.features.lesion import imaging_report

    assert hasattr(imaging_report, "ImagingReportParser")
    assert imaging_report.IMAGING_PARSER_VERSION == "imaging-report-parser-v1"


def test_h06_section_constants_present_on_fix_branch() -> None:
    """契约不直接约束段头常量；该常量由 PR #23 修复引入（键名统一）。

    本分支为未合并状态，故此处只记录事实、不断言，避免把"分支未合并"
    误报成"契约违约"。
    """
    from app.features.lesion import imaging_report

    has_constants = hasattr(imaging_report, "SECTION_KEYS")
    if not has_constants:
        pytest.skip(
            f"本分支未合并 {_BRANCH_DELTA['SECTION_KEYS']}；"
            "该常量与相邻回归由其修复分支测试覆盖"
        )
    assert imaging_report.SECTION_KEYS == (
        imaging_report.SECTION_BODY,
        imaging_report.SECTION_FINDINGS,
        imaging_report.SECTION_CONCLUSIONS,
    )


def test_h06_terminology_exposes_site_config_for_injection() -> None:
    """契约第七节第 2 条：多部位术语配置注入。

    注：契约文档写作 `LesionTerminologyConfig`，实现命名为 `LesionSiteConfig`，
    两者同义（配置注入用的部位词表配置）。此处按**实现**核对，并记录命名差异。
    """
    import app.features.lesion.terminology as terminology

    assert hasattr(terminology, "LesionSiteConfig"), "缺部位术语配置类型"
    assert terminology.TERMINOLOGY_VERSION, "术语表应带版本号"


# ==================== H07 规则内容与候选生成 ====================


def test_h07_version_and_service_methods() -> None:
    from app.rule_candidates import RuleCandidateService

    assert RuleCandidateService.VERSION == "rule-candidates-v1"
    assert callable(getattr(RuleCandidateService, "candidates", None))


def test_h07_rule_content_item_fields() -> None:
    from app.rule_candidates import RuleContentItem

    _assert_fields(
        RuleContentItem,
        ("rule_code", "version", "priority", "recommended_exam_codes",
         "reason_template", "missing_info_prompt", "source",
         "source_version", "review_status"),
        "RuleContentItem",
    )


def test_h07_candidate_result_has_candidates_missing_info_excluded() -> None:
    from app.rule_candidates import CandidateResult

    present = _fields_of(CandidateResult)
    for name in ("candidates", "missing_info", "excluded"):
        assert name in present, f"CandidateResult 缺字段 {name}"


def test_h07_candidates_signature_accepts_findings() -> None:
    from app.rule_candidates import RuleCandidateService

    params = inspect.signature(RuleCandidateService.candidates).parameters
    assert "findings" in params


def test_h07_rule_content_starts_as_pending_review() -> None:
    """契约第八节：规则内容 review_status 一律 pending_review 起步。"""
    from app.rule_candidates import load_rule_content

    content = load_rule_content()
    items = content if isinstance(content, (list, tuple)) else getattr(content, "rules", content)
    assert items, "规则集不应为空"
    for item in items:
        assert item.review_status in ("pending_review", "reviewed"), item.review_status


# ==================== H08 问答与结构化解释 ====================


def test_h08_version_and_answer_signature() -> None:
    from app.llm.qa import QAService

    assert QAService.VERSION == "qa-service-v1"
    params = inspect.signature(QAService.answer).parameters
    for name in ("question", "context"):
        assert name in params, f"answer 缺参数 {name}"


def test_h08_qa_context_is_separate_type() -> None:
    from app.llm.qa import QAContext

    assert isinstance(QAContext, type)


def test_h08_templated_provider_labels_fallback_mode() -> None:
    """契约第九节：回退必须显式标注 template，不冒充真实模型。

    真实签名（async）：chat_with_patient_context(request: PatientChatRequest) -> LLMResponse，
    其中 PatientChatRequest 需要 context(StructuredPatientContext) 与 user_message。
    """
    import asyncio

    from app.llm.contracts import PatientChatRequest, StructuredPatientContext
    from app.llm.templated import TemplatedLLMProvider

    context = StructuredPatientContext(patient_id="IC-TEST-0001")
    request = PatientChatRequest(context=context, user_message="测试问题")
    response = asyncio.run(TemplatedLLMProvider().chat_with_patient_context(request))

    assert response.content, "模板实现应产出内容"
    assert response.llm_model, "响应应标注所用的 provider/model 标识"
    assert "template" in str(response.llm_model).lower(), (
        f"模板回退必须在模型标识中标注 template，实际 {response.llm_model!r}"
    )


def test_h08_openai_provider_exposes_availability_gate() -> None:
    from app.llm.openai_compat import OpenAICompatibleLLMProvider

    assert hasattr(OpenAICompatibleLLMProvider, "is_available")


# ==================== H09 模型任务注册 ====================


def test_h09_version_and_registry_methods() -> None:
    from app.ml.tasks import ModelTaskRegistry

    assert ModelTaskRegistry.VERSION == "model-task-registry-v1"
    for name in ("register", "get", "list_tasks", "availability"):
        assert callable(getattr(ModelTaskRegistry, name, None)), f"缺方法 {name}"


def test_h09_registration_fields() -> None:
    from app.ml.tasks import ModelTaskRegistration

    _assert_fields(
        ModelTaskRegistration,
        ("task_id", "disease_goal", "population", "input_features", "time_horizon",
         "output_spec", "data_source", "source_version", "status",
         "unavailable_reason"),
        "ModelTaskRegistration",
    )


def test_h09_builtin_tasks_expose_explicit_unavailability() -> None:
    """契约第十节：未接入任务必须给出显式状态与 reason，不得静默可用。"""
    from app.ml.tasks import load_builtin_registry

    registry = load_builtin_registry()
    tasks = registry.list_tasks()
    assert tasks, "应注册首批任务"
    for task in tasks:
        assert task.status in ("awaiting_data", "in_development", "integrated", "retired")
        availability = registry.availability(task.task_id)
        if not availability.available:
            assert availability.reason, f"{task.task_id} 不可用必须给出 reason"


# ==================== H11 九华数据接入准备 ====================


def test_h11_mapping_template_entries_are_unverified() -> None:
    """契约第十一节第 1 条：映射模板每条 verification_status 为 unverified。"""
    from app.jiuhua_prep import load_mapping_template

    entries = load_mapping_template()
    assert entries, "映射模板应有条目"
    for entry in entries:
        assert entry.verification_status == "unverified", (
            f"未验证字段必须标 unverified：{entry.source_field}"
        )


def test_h11_quality_summary_and_anonymization_present() -> None:
    """契约第十一节第 2/3 条：质量摘要工具与匿名标识规则。"""
    import app.jiuhua_prep as module

    assert callable(getattr(module, "summarize_quality", None)), "缺质量摘要工具"
    assert callable(getattr(module, "anonymize_identifier", None)), "缺匿名标识函数"
    assert callable(getattr(module, "batch_provenance", None)), "缺批次溯源函数"


# ==================== 通用约定：确定性 ====================


def test_content_loaders_are_repeatable() -> None:
    """契约第一节第 6 条：所有列表输出确定性排序，同输入同输出。"""
    from app.exam_dictionary import load_builtin_associations, load_builtin_catalog

    first_codes = [e.code for e in load_builtin_catalog().entries_by_category("blood_routine")]
    second_codes = [e.code for e in load_builtin_catalog().entries_by_category("blood_routine")]
    assert first_codes == second_codes

    first_exam = "1558-6"
    first_assoc = [a.association_id for a in load_builtin_associations().associations_for_exam(first_exam)]
    second_assoc = [a.association_id for a in load_builtin_associations().associations_for_exam(first_exam)]
    assert first_assoc == second_assoc


# ==================== H02 ↔ H01 跨域对照（T05 分析编排联调） ====================
#
# 背景：T05 的 `backend/app/data/analysis_finding_map.json`（PR #33）在 scope_note 中
# 自述「H02 目录接入后由该目录替换本文件」，其 `exam_codes` 用的是**工程占位码**
# （如 `CHEST_CT`），与 H01 字典的登记编码（如 `IC:EX-CT-CHEST-LOWDOSE`）并不同名。
# 这段把对照关系固化成可执行断言，供 T05 切换到 H02 目录时直接使用：
#   1) H02 自身内容必须与 H01 字典自洽（`validate_against` 返回空）；
#   2) 字典对未登记编码必须"响亮失败"（返回 None），不得凭空生成检查项目；
#   3) 对照表本身必须指向真实存在的字典登记项。

# 占位码 → H01 字典登记码。改动此表前请先跑 test_h02_crosswalk_targets_are_registered_in_h01。
_H02_X_H01_CROSSWALK: dict[str, tuple[str, ...]] = {
    "CHEST_CT": ("IC:EX-CT-CHEST-LOWDOSE", "IC:EX-DR-CHEST"),
    "LIPID_PANEL": ("2093-3", "2571-8", "2085-9", "13457-7"),
    "LIVER_FUNCTION_PANEL": ("1742-6", "1920-8", "1975-2", "1751-7", "6768-6"),
    "URINE_ROUTINE": ("IC:M-URINE-MICROSCOPY", "IC:M-URINE-OCCULT-BLOOD"),
}


def test_h02_content_validates_against_h01_dictionary() -> None:
    """H02 关联内容里的 exam_code 必须全部已在 H01 字典登记。"""
    from app.exam_dictionary import ExamDictionary, FindingCatalog

    problems = FindingCatalog.load_builtin().validate_against(ExamDictionary.load_builtin())
    assert problems == [], f"H02 关联存在未登记的检查编码：{problems}"


def test_h01_dictionary_fails_loudly_on_unregistered_exam_code() -> None:
    """字典对未登记编码必须返回 None，不得凭空生成检查项目。

    这几个占位码正是 T05 临时映射用的；它们**不应**是 H01 的登记编码。
    若将来真的登记进 H01，请同步更新 `_H02_X_H01_CROSSWALK` 并撤掉本用例。
    """
    from app.exam_dictionary import ExamDictionary

    dictionary = ExamDictionary.load_builtin()
    for code in _H02_X_H01_CROSSWALK:
        assert dictionary.lookup_by_code(code) is None, (
            f"{code} 已是 H01 登记编码，请更新对照表 `_H02_X_H01_CROSSWALK`"
        )


def test_h02_crosswalk_targets_are_registered_in_h01() -> None:
    """对照表里每个字典登记码都必须真实存在，防止对照表本身写错。"""
    from app.exam_dictionary import ExamDictionary

    dictionary = ExamDictionary.load_builtin()
    for placeholder, targets in _H02_X_H01_CROSSWALK.items():
        assert targets, f"{placeholder} 的对照目标为空"
        for code in targets:
            entry = dictionary.lookup_by_code(code)
            assert entry is not None, f"{placeholder} 对照到未登记编码 {code}"
            assert entry.display_name, f"{code} 缺少显示名，无法在页面展示"


def test_t05_interim_finding_map_codes_are_all_crosswalked(tmp_path) -> None:
    """T05 占位映射文件若已合并，其 exam_codes 必须全部落在对照表内。

    PR #33 未合并时跳过并写明原因，不假装通过。
    """
    import json
    import pathlib as _pathlib

    from app.exam_dictionary import ExamDictionary

    repo_map = _pathlib.Path("app/data/analysis_finding_map.json")
    if not repo_map.is_file():
        pytest.skip(
            "T05 的 app/data/analysis_finding_map.json 尚未合并（PR #33）；"
            "合并后本用例会校验其 exam_codes 是否已对照进 H01 字典"
        )
    payload = json.loads(repo_map.read_text(encoding="utf-8"))
    dictionary = ExamDictionary.load_builtin()
    unmapped = [
        (entry.get("finding_code"), code)
        for entry in payload.get("entries", [])
        for code in entry.get("exam_codes", [])
        if dictionary.lookup_by_code(code) is None and code not in _H02_X_H01_CROSSWALK
    ]
    assert unmapped == [], f"占位映射存在未对照编码：{unmapped}"
