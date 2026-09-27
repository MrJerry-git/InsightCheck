# 自制样例与内容覆盖清单（H12）

负责人：王宏锦（WHJ-2007）。日期：2026-09-27。状态：自制工程样例（文件内标注"自制样例"或作为测试夹具使用），**不是真实体检数据**，不用于任何医学有效性结论。

样例位置：`backend/tests/fixtures/h12_samples/`。联调链路测试：`backend/tests/integration_h12/`：

- `test_sample_chain.py`：样例 → H03 解析（H01 字典映射）→ H05 跨系统汇总 → H02 关联 → H07 规则候选。
- `test_full_chain.py`：**真实 CSV/Excel/PDF 文件 → 校对队列 → 分析 → 规则候选 → 三档方案**的整体联调（含无法计算项传至页面、证据回溯、locator 保留），以及**真实 OCR 引擎**的 H04→T03→H03→H05/H07→方案链路（第六节）。
- `test_service_contracts.py`：**按 `docs/H_SERIES_SERVICE_CONTRACTS.md` 逐项核对各模块实际接口**（版本号 / 字段名 / 签名形状 / 硬性规则），防止契约文档与实现脱节。

## 〇、本分支的同步状态（2026-09-27 重做，重要）

PR #29 审核（2026-09-23）指出：**本分支尚未吸收 #19/#21/#23/#24/#26 的最新修复，不能通过合并汇总 PR 把旧阻断实现重新带入**。本轮按此重做：

**1. 本分支已重新合并 main**（main head `a9147b93`）。main 上已合入的修复因此全部吸收：

| 来源 PR | 模块 | 修复内容 | 状态 |
| --- | --- | --- | --- |
| #19 | H03 `app/tabular_parsing/` | 缺单位记录标 `unit_missing`，**不再赋标准单位**、保留原值 | ✅ 已在 main，本分支直接使用 |
| #23 | H06 `app/features/lesion/` | 段落标题不再导致 KeyError（`SECTION_KEYS` 语义对齐） | ✅ 已在 main |
| #24 | H07 `app/rule_candidates/` | 冲突排除生效、缺年龄不推荐（转待确认） | ✅ 已在 main |
| #26 | H08 `app/llm/` | 引用与所引内容绑定（错配摘除） | ✅ 已在 main |
| #11 | H01/H02 | 内置数据文件 `.gitignore` 例外 + 参考区间边界校验 | ✅ 已在 main |
| #25/#27 | H09/H11 | 模型任务注册、九华数据准备 | ✅ 已在 main |

**2. 尚未合入 main 的 #20/#21 的最终修复，已逐项覆盖进本分支**（本分支作为汇总分支必须携带它们才能做端到端联调）：

| 来源 PR | 模块 | 修复内容 | 本分支落点 |
| --- | --- | --- | --- |
| #20 @ `8c45837b` | H04 | 渲染后端改 pypdfium2（宽松许可）；逐页渲染 OCR；测试 fitz-free + 可选引擎显式 skip；`ocr` extra | `backend/app/report_extraction/*`、`backend/scripts/ocr_smoke.py`、`backend/tests/report_extraction/*`、`docs/{ocr-run-record.json,REPORT_EXTRACTION_OCR_RUN.md}` |
| #21 @ `591bff71` | H05 | 缺单位从**全部数值原记录**识别（不要求先有可比较数值），保留原值/日期/来源 | `backend/app/cross_system/*`、`backend/tests/cross_system/*` |

**3. `backend/pyproject.toml` 做真正的三方合并**：以 main 为基准合入 #20 的 `pypdf` 依赖与 `ocr` extra，**不回灌 #20 分支上更旧的依赖列表**（避免把 main 已新增的 `httpx/pillow/pypdfium2/openpyxl` 删掉）。

> 结论：本分支当前树 = main + #20/#21 最终修复 + H12 样例/联调套件。**不再是"用汇总 PR 绕过阻断项"**。
> H10 组件清单（`docs/REUSABLE_COMPONENTS.md`）随 #28 更新，本分支携带其最新版。

## 一、样例清单与覆盖矩阵

| 样例文件 | 类别（任务书第二节） | 值形态 | 覆盖点 | 验证测试 |
| --- | --- | --- | --- | --- |
| h12_blood_routine.csv | 血常规 | 数值 | 白细胞/红细胞/血红蛋白/血小板/MCV/中性粒细胞比率；6 项全部命中字典编码 | `test_blood_routine_sample_parses_fully_mapped`、`test_real_csv_file_parses_and_queues_unmapped` |
| h12_urine_stool.csv | 尿液与粪便检查 | 定性 + 文字 | 尿蛋白"±"（登记允许值）、便潜血"弱阳性"（**未登记值→保留原文入队**）、尿/便镜检文字透传 | `test_urine_stool_sample_covers_qualitative_and_text` |
| h12_biochemistry_lipids.csv | 肝肾生化 + 糖代谢血脂 | 数值 | 13 项生化血脂；"偏高"提示列保留（report_flag）；参考区间前缀（<、≥）原样保留不猜测 | `test_biochemistry_sample_flags_abnormalities_from_report_hint` |
| h12_unknown_metrics.csv | 扩展项目（未登记） | 数值 + 文字 | 未知指标（D-二聚体、超敏CRP）→ 待映射队列，不丢弃；机构自定义文字条目 | `test_unknown_metric_sample_queues_without_dropping` |
| h12_ecg_report.txt | 心电图及功能检查 | 文字结论 | 心电图所见/诊断段落；进汇总做时间线对照，不做异常判定 | `test_text_samples_feed_summarizer_without_judgment` |
| h12_thyroid_us.txt | 超声/放射影像报告 | 文字 + 病灶描述 | 甲状腺超声所见/提示；病灶句候选由 H06 解析（`tests/lesion/test_multisite_and_revisions.py`） | `test_text_samples_feed_summarizer_without_judgment` |

同形样例（由 `test_full_chain.py` 在测试内真实生成，覆盖 CSV/Excel/PDF/扫描件四种入口）：

| 入口 | 生成方式 | 覆盖点 | 验证测试 |
| --- | --- | --- | --- |
| 真实 CSV 文件 | `tmp_path` 写入 UTF-8 CSV | 走 `TabularReportParser` 全流程，含中文表头与异常提示列 | `test_real_csv_file_parses_and_queues_unmapped` |
| 真实 xlsx 文件 | openpyxl 写入，与 CSV 同内容 | 两个入口产出等价的校对队列 | `test_real_xlsx_bytes_parse_identically_to_csv` |
| 真实 PDF（文本层） | 手写最小 PDF，含 `/Contents` 文本流 | 文本层可提取、locator（页码/行号）保留 | `test_real_pdf_text_layer_extracts_with_locators` |
| 真实 PDF（扫描件，无引擎） | 手写无文本层 PDF | **显式报告"不完整"，不谎报成功** | `test_scanned_pdf_without_engine_is_explicitly_incomplete` |
| **真实扫描件 + 真实 OCR 引擎** | Pillow 绘制中文报告 → 嵌入 PDF（无文本层） | 真实逐页 OCR → 文本行 → H03 → H05/H07 → 三档方案 | `test_real_ocr_engine_to_plan_chain`（真实引擎） |
| 扫描件 + OCR 替身 | Pillow 图片页 + FakeOcr/FakeRenderer | 同一链路在无引擎环境也可回归 | `test_mock_ocr_engine_to_plan_chain`（模拟引擎） |

形态覆盖核对：数值 ✓（血常规、生化）、定性 ✓（尿便）、文字 ✓（心电、影像、镜检）、病灶 ✓（甲状腺超声，H06 测试）。**不能用一份肺部样例代表全类别**——本清单逐类别登记。

## 二、失败情形覆盖

| 情形 | 样例/测试 |
| --- | --- |
| 未登记指标 | h12_unknown_metrics.csv → 待映射队列（不丢弃、不自动解释）；`test_unknown_metric_sample_queues_without_dropping` |
| 未登记定性值 | h12_urine_stool.csv 便潜血"弱阳性" → unregistered_qualitative |
| 单位无换算依据 | `test_proofread_queue_separates_computable_from_not`（肌酐未知单位 → unit_unconverted，不可计算） |
| **缺失单位（#19 P1）** | **已合入 main**：`unit_missing` 状态 + 保留原值；`test_proofread_queue_separates_computable_from_not` 已**收紧为断言 `computable is False`** |
| **缺单位跨模块传播（#21 P1）** | `tests/cross_system/test_summarizer.py::test_real_h03_to_h05_missing_unit_is_surfaced_for_follow_up`（真实 H03→H05）；本分支 `test_real_ocr_engine_to_plan_chain` 亦覆盖 |
| 数值无法解析 | tests/tabular_parsing（原值保留 + 逐项错误） |
| 表头不识别 / 空列 / 坏 Excel | tests/tabular_parsing + test_excel |
| 参考区间缺失 | tests/cross_system（no_reference，不编造阈值）；`test_uncomputable_items_are_visible_not_silently_dropped` 断言无法计算项原因可见 |
| 倒置/布尔/非有限参考区间 | `tests/exam_dictionary/test_catalog.py`（`aa2062be`，已在 main） |
| 决策日期之后的记录 | tests/cross_system（显式排除并留痕） |
| 未识别版式 / 扫描件 / 无 OCR 引擎 | tests/report_extraction（显式失败状态）；`test_scanned_pdf_without_engine_is_explicitly_incomplete`、`test_unknown_layout_is_reported_not_guessed` |
| 跨部位关联 | tests/lesion（算法不自动匹配 + 人工关联拒绝） |
| 引用不存在的证据 | tests/llm（引用摘除并提示人工核对） |
| 草稿规则默认不启用 | tests/rule_candidates（draft 默认排除） |
| 冲突组优先级 | tests/rule_candidates（更高优先级胜出，落败规则依据移除）— **已在 main** |
| 年龄未知时的年龄限定规则 | tests/rule_candidates（缺年龄→待确认，不推荐）— **已在 main** |

## 三、H→T→前端链路联调（本次补充）

`test_full_chain.py` 覆盖 PR #29 审核要求的"实际 CSV/Excel/PDF→校对→分析→候选→方案"链路：

1. **文件 → 解析**：真实 CSV/Excel/PDF 三种入口在测试内实际生成并解析，非夹具字典直接喂入。
2. **解析 → 校对队列**：`to_proofread_queue()` 输出每条的 `computable` 与显式 `reason`，**无法计算项必须带原因进入页面**（C03 校对界面消费者），不允许静默丢弃。判定以 **H03 状态机**为准（`unit_missing` / `unit_unconverted` / `invalid_value` / `unregistered_qualitative`）。
   - 断言：`test_proofread_queue_separates_computable_from_not`、`test_uncomputable_items_are_visible_not_silently_dropped`。
3. **校对 → 分析**：`build_observations()` + `with_reference()` 演示 T04 编排层对接；`as_of` 决策日期由 T04 固定并传递；运行版本记录 `cross-system-summary-v1`。
4. **分析 → 候选**：H05 异常 + H02 关联 → `NormalizedFinding`；`RuleCandidateService` 输出直接供 plan_builder 消费；`REVIEW_REQUIRED` 状态与 `rule_set_version="rule-content-v1"` 显式传递。
5. **候选 → 方案**：构造 `PlanBuildRequest`（`BudgetSpec(limit_cents=500_000, currency="CNY")`）走通三档方案产出，并断言**方案内每条建议可回溯到原始 `record_ref`**（`test_plan_items_trace_back_to_candidate_evidence`）。
6. **确定性**：同输入两次执行产出完全一致（`test_full_chain_is_deterministic_end_to_end`）。
7. **locator 保留**：Excel/PDF 的行号、页码在链路中不丢失（`test_proofread_locator_preserved_for_traceback`）。
8. **待复核与冲突可见**：`test_plan_keeps_requires_review_and_reports_conflicts`、`test_missing_info_and_excluded_reach_the_page`。

### 3.1 H04→T03→H03→H05/H07→方案：真实引擎 vs 模拟（复核要求注明）

| 测试 | 引擎 | 说明 |
| --- | --- | --- |
| `test_real_ocr_engine_to_plan_chain` | **真实**：pypdfium2 渲染 + rapidocr-onnxruntime OCR | 中文报告由 Pillow 绘制→嵌入 PDF（无文本层）→**真实逐页 OCR**→文本行经 T03 正则切成行→真实 H03/H01/H05/H02/H07/PlanBuilder。引擎或系统中文字体缺失时**显式 skip** |
| `test_mock_ocr_engine_to_plan_chain` | **模拟**：`FakeOcr` + `FakeRenderer` | 仅替换"图像→文本"一步，下游全部真实；保证无引擎环境也能回归链路形状 |

其余 H12 测试的引擎属性：

| 测试 | 引擎属性 |
| --- | --- |
| `test_real_xlsx_bytes_parse_identically_to_csv` | **真实** openpyxl 读写 xlsx 字节 |
| `test_real_pdf_text_layer_extracts_with_locators` | **真实** pypdf 读文本层 |
| `test_scanned_pdf_without_engine_is_explicitly_incomplete` | **无引擎**（验证显式不可用分支） |
| `tests/report_extraction/*` 中 `test_fully_scanned_pdf_calls_ocr_when_engine_injected` 等 | **模拟**（`FakeOcr`/`FakeRenderer`，精确控制逐页调用） |
| `tests/report_extraction/test_real_engine_scanned_and_mixed_pdf` | **真实** pypdfium2 + rapidocr（未装则 skip） |

与 T 系列的具体对接约定（沿用）：

- **T03 导入**：CSV/Excel 行来自 T03 文件解析（编码探测/大小限制归 T03）；扫描件文本行来自 H04 逐页 OCR 后由 T03 转成行；`ParsedTabularReport` 的 `entries/issues/unmapped` 对接 C03 候选、错误、待映射三区展示。
- **T04 分析编排**：`Observation` 映射与 `as_of` 传递见上。
- **T05 候选汇总**：同一检查多问题只计一次已在服务内去重。
- **T10 问答**：`QAContext` 证据条目 ref_id 使用 `record_ref`，保证引用可回溯。

## 四、覆盖状态

- [x] 第二节全部 9 类别有明确标注的自制样例或既有 demo（基础信息/问卷与体格检查类文字条目经 h12 样例 + exam_catalog 覆盖；影像类经 h12_thyroid_us.txt 与 H06 测试覆盖）
- [x] 数值 / 定性 / 文字 / 病灶四种形态均有可运行样例与测试
- [x] 失败情形（解析失败、未知项、缺单位、单位无依据、版式不识别、引用不存在等）均有测试
- [x] **实际 CSV/Excel/PDF 文件 → 校对 → 分析 → 候选 → 方案的整体联调**（`test_full_chain.py`）
- [x] **H04→T03→H03→H05/H07→方案**链路，含**真实 OCR 引擎**用例（缺引擎时显式 skip）
- [x] **无法计算项带显式原因传至页面**（校对队列 `computable` + `reason`）
- [x] **本分支已重新合并 main，吸收 #11/#19/#23/#24/#25/#26/#27 的最终实现**
- [x] **#20/#21 的最终修复已逐项覆盖**，端到端联调在其真实实现上运行
- [ ] **#20/#21 合并进 main** —— 本分支已携带其修复；待各自 PR 合并后本分支再做一次空合并即可
- [ ] 普通新建档案的端到端浏览器流程（M4 共同验收，依赖 C/T 系列）
- [ ] 真实机构版式样例（待本机构报告适配任务）

## 五、验证记录

执行环境：`backend` 目录，Python 3.12.10 venv（含 pypdfium2 5.13.0 + rapidocr-onnxruntime 1.4.4，故真实 OCR 引擎用例实际运行而非 skip）。

```
$ python -m pytest tests -o addopts=""
542 passed, 4 skipped in 64.88s
```

子系统：

| 目录/文件 | 结果 |
| --- | --- |
| `tests/integration_h12/`（合计） | **63 passed, 1 skipped** |
| ├─ `test_sample_chain.py` | 10 passed |
| ├─ `test_full_chain.py` | 16 passed（含 1 条真实 OCR 引擎链路 + 1 条模拟链路） |
| └─ `test_service_contracts.py` | 37 passed, 1 skipped |
| `tests/exam_dictionary/` | 29 passed（test_catalog 19 + test_associations 10） |

4 处 skip 全部**有明确原因、不是被跳过的失败**：

1. `test_nlst_cohort.py` / `test_research.py`：本机未装 `pyarrow`（环境缺依赖）；
2. `test_service_contracts.py`：T05 临时映射文件未合并（PR #33），合并后自动校验；
3. `test_report_extraction.py`：rapidocr 已安装，跳过"引擎不可用"分支（该分支已由未装环境的成员验证）。

### 契约一致性检查结果

`test_service_contracts.py` 对照 `docs/H_SERIES_SERVICE_CONTRACTS.md` 核对结论：

- **版本号全部一致**：`exam-dictionary-v1`、`finding-catalog-v1`、`tabular-parsing-v1`、`report-extraction-v1`、`report-structuring-v1`、`cross-system-summary-v1`、`imaging-report-parser-v1`、`rule-candidates-v1`、`qa-service-v1`、`model-task-registry-v1`。
  说明：实现把版本号放在**类属性 `VERSION`**（非实例属性 `version`），文档描述用 `version: str`；语义一致，此处按实现核对并记录该形态差异。
- **硬性规则通过**：H02 `relation_type` 仅取提示/观察/危险因素，无确诊口径；H11 映射模板 14 条全部 `unverified`；H09 未接入任务均给出显式 `unavailable_reason`（`artifact_missing` / `review_not_frozen`）；H07 规则内容 `pending_review` 起步。
- **已记录的两处命名差异（不构成阻断，供 T 系列对齐）**：
  1. 契约写 `LesionTerminologyConfig`，实现为 `LesionSiteConfig`（同义：部位词表配置）。
  2. 契约写字典加载器 `ExamDictionary.lookup` 等为实例方法，实现一致；但文档中 `version` 字段应改注为 `VERSION` 类属性以与实际形态对齐。
- **上一轮的 H06 `SECTION_KEYS` skip 已消失**：#23 已合入 main，本分支直接使用修复实现，原先"显式 skip 并标注来源"的用例现在真实通过。

> 契约文档与实现的这些措辞差异属**文档待更新**，随 #28（H10）与后续文档 PR 一并修订。

### H02 ↔ H01 跨域编码对照（T05 分析编排联调）

对 T 系列在途 PR 逐一核对后发现的**真实跨域缺口**（非猜测，已在本分支用测试固化）：

T05（PR #33 `feat/analysis-runs`）新增 `backend/app/data/analysis_finding_map.json`。该文件在自己的 `scope_note` 里写明「**H02 目录接入后由该目录替换本文件**」——即它自认是临时替身，这没问题；但它用 `exam_codes` 引用的是**工程占位码**，而 H01 字典用的是登记编码，两者不同名：

| T05 占位码 | 在 H01 字典是否存在 | H01 字典中的对应登记项 |
| --- | --- | --- |
| `CHEST_CT` | ❌ 不存在 | `IC:EX-CT-CHEST-LOWDOSE`（低剂量胸部CT）、`IC:EX-DR-CHEST`（胸部正位摄影） |
| `LIPID_PANEL` | ❌ 不存在 | `2093-3` 总胆固醇、`2571-8` 甘油三酯、`2085-9` HDL-C、`13457-7` LDL-C |
| `LIVER_FUNCTION_PANEL` | ❌ 不存在 | `1742-6` ALT、`1920-8` AST、`1975-2` 总胆红素、`1751-7` 白蛋白、`6768-6` 碱性磷酸酶 |
| `URINE_ROUTINE` | ❌ 不存在 | `IC:M-URINE-MICROSCOPY`（尿沉渣镜检）、`IC:M-URINE-OCCULT-BLOOD`（尿潜血定性） |

即：T05 的占位映射若不经对照直接喂给 H01 字典，`lookup_by_code` 会**全部返回 `None`**（已实测），候选检查项目无法解析。这正是 H12「服务联调」应当拦下的问题。

本分支 4 条断言固化该对照（`test_service_contracts.py`）：

| 断言 | 作用 |
| --- | --- |
| `test_h02_content_validates_against_h01_dictionary` | H02 自身 37 条关联的 `exam_code` 与 H01 字典自洽（`validate_against` 返回 `[]`） |
| `test_h01_dictionary_fails_loudly_on_unregistered_exam_code` | 字典对占位码返回 `None`——**不凭空生成检查项目**，与 T05 自己的承诺一致 |
| `test_h02_crosswalk_targets_are_registered_in_h01` | 上表每个登记码真实存在且有显示名，防止对照表本身写错 |
| `test_t05_interim_finding_map_codes_are_all_crosswalked` | #33 合并后自动校验其 `exam_codes` 是否已全部对照；未合并时**显式 skip 并写明原因** |

**结论与归属**：不需要改 T05 的代码即可继续——上表即为 T05 切换到 H02 目录时可直接采用的对照。已按团队约定（规则/内容由王宏锦提出、落地由王天一执行）在 PR #29 记录并请张家睿裁决归属，不在 H12 分支代为修改 `app/data/` 下的 T 系列文件。
