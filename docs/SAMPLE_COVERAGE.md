# 自制样例与内容覆盖清单（H12）

负责人：王宏锦（WHJ-2007）。日期：2026-09-22。状态：自制工程样例（文件内标注"自制样例"或作为测试夹具使用），**不是真实体检数据**，不用于任何医学有效性结论。

样例位置：`backend/tests/fixtures/h12_samples/`。联调链路测试：`backend/tests/integration_h12/`：

- `test_sample_chain.py`：样例 → H03 解析（H01 字典映射）→ H05 跨系统汇总 → H02 关联 → H07 规则候选。
- `test_full_chain.py`：**真实 CSV/Excel/PDF 文件 → 校对队列 → 分析 → 规则候选 → 三档方案**的整体联调（含无法计算项传至页面、证据回溯、locator 保留）。
- `test_service_contracts.py`：**按 `docs/H_SERIES_SERVICE_CONTRACTS.md` 逐项核对各模块实际接口**（版本号 / 字段名 / 签名形状 / 硬性规则），防止契约文档与实现脱节。

## 〇、本分支包含的修复与合并状态（重要）

本分支（feat/sample-coverage-suite）此前是"H01—H11 全功能分支的汇总"，PR #29 审核已明确指出**不能通过合并汇总 PR 绕过各分支自身的阻断项**。按审核意见，本分支改为：

**1. 已吸收 main 已合并的 #11 最新修正（本次变更）**

| 来源提交 | 内容 | 本分支落点 |
| --- | --- | --- |
| `023b5350` | 提交被 `.gitignore` 误伤的 exam dictionary 内置数据文件（H01 审查 P1） | `.gitignore` 例外规则 + `backend/app/exam_dictionary/data/{exam_catalog,finding_associations,packages/demo_package}.json` |
| `aa2062be` | 拒绝倒置、布尔、非有限参考区间边界（H01 审查 P2） | `backend/app/exam_dictionary/catalog.py` `_parse_reference_range` + `backend/tests/exam_dictionary/test_catalog.py` 四条回归 |
| `6071ad15` | 提交被 `.gitignore` 误伤的九华字段映射模板（H11） | `.gitignore` 例外规则 + `backend/app/jiuhua_prep/data/jiuhua_field_mapping_template.json` |

以上文件已与 main 逐字节一致（SHA1 对齐），不再依赖分支自身的旧版实现。

**2. 本分支内所包含的 H 模块，其阻断项修复在各自分支，不在本分支**

| 模块 | 阻断项（PR #29 审核） | 修复分支/提交 | 本分支当前状态 |
| --- | --- | --- | --- |
| #19 H03 | 缺失单位被赋标准单位 | `feat/tabular-parsing` @ `b31a1e6`（新增 `unit_missing`） | **未合并**：本分支仍是旧版，`空腹血糖` 空单位被当作 `mapped` |
| #20 H04 | 扫描/混合 PDF 不完整仍报成功 | `feat/report-extraction` @ `d3e873c` | **未合并** |
| #21 H05 | 未知单位仍参与趋势比较 | `feat/cross-system-analysis` @ `3fd6576` | **未合并** |
| #23 H06 | 段落标题导致 KeyError | `feat/imaging-lesion-multisite` @ `565d45b` | **未合并** |
| #24 H07 | 冲突排除无效、缺年龄仍推荐 | `feat/rule-candidates` @ `ad88661` | **未合并** |
| #26 H08 | 引用与内容未绑定 | `feat/llm-qa-service` @ `8598aac` | **未合并** |

因此本清单**不作为 2.0 完成证明**。待上述修复分支合并进 main 后，本分支应 rebase/重新合并 main，再重跑 `backend/tests/integration_h12/` 作为整体验收。`test_full_chain.py` 中已对上述差异做了显式注释（见 `test_proofread_queue_separates_computable_from_not` 的 docstring：注明本分支 #19 仍为修复前版本，故该断言尚未收紧为 `computable is False`），不复用旧版语义冒充已修复。

**合并安全检查**：本分支所有 `.gitignore` 例外均为精确路径例外（`!backend/app/**/data/**` 类），不改动 `data/` 的忽略规则本身，与 main 的 `88c34211c9` 版本一致。

## 一、样例清单与覆盖矩阵

| 样例文件 | 类别（任务书第二节） | 值形态 | 覆盖点 | 验证测试 |
| --- | --- | --- | --- | --- |
| h12_blood_routine.csv | 血常规 | 数值 | 白细胞/红细胞/血红蛋白/血小板/MCV/中性粒细胞比率；6 项全部命中字典编码 | `test_blood_routine_sample_parses_fully_mapped`、`test_real_csv_file_parses_and_queues_unmapped` |
| h12_urine_stool.csv | 尿液与粪便检查 | 定性 + 文字 | 尿蛋白"±"（登记允许值）、便潜血"弱阳性"（**未登记值→保留原文入队**）、尿/便镜检文字透传 | `test_urine_stool_sample_covers_qualitative_and_text` |
| h12_biochemistry_lipids.csv | 肝肾生化 + 糖代谢血脂 | 数值 | 13 项生化血脂；"偏高"提示列保留（report_flag）；参考区间前缀（<、≥）原样保留不猜测 | `test_biochemistry_sample_flags_abnormalities_from_report_hint` |
| h12_unknown_metrics.csv | 扩展项目（未登记） | 数值 + 文字 | 未知指标（D-二聚体、超敏CRP）→ 待映射队列，不丢弃；机构自定义文字条目 | `test_unknown_metric_sample_queues_without_dropping` |
| h12_ecg_report.txt | 心电图及功能检查 | 文字结论 | 心电图所见/诊断段落；进汇总做时间线对照，不做异常判定 | `test_text_samples_feed_summarizer_without_judgment` |
| h12_thyroid_us.txt | 超声/放射影像报告 | 文字 + 病灶描述 | 甲状腺超声所见/提示；病灶句候选由 H06 解析（`tests/lesion/test_multisite_and_revisions.py`） | `test_text_samples_feed_summarizer_without_judgment` |

同形样例（由 `test_full_chain.py` 在测试内真实生成，覆盖 CSV/Excel/PDF 三种入口）：

| 入口 | 生成方式 | 覆盖点 | 验证测试 |
| --- | --- | --- | --- |
| 真实 CSV 文件 | `tmp_path` 写入 UTF-8 CSV | 走 `TabularReportParser` 全流程，含中文表头与异常提示列 | `test_real_csv_file_parses_and_queues_unmapped` |
| 真实 xlsx 文件 | openpyxl 写入，与 CSV 同内容 | 两个入口产出等价的校对队列 | `test_real_xlsx_bytes_parse_identically_to_csv` |
| 真实 PDF（文本层） | 手写最小 PDF，含 `/Contents` 文本流 | 文本层可提取、locator（页码/行号）保留 | `test_real_pdf_text_layer_extracts_with_locators` |
| 真实 PDF（扫描件） | 手写无文本层 PDF | **显式报告"不完整"，不谎报成功** | `test_scanned_pdf_without_engine_is_explicitly_incomplete` |

形态覆盖核对：数值 ✓（血常规、生化）、定性 ✓（尿便）、文字 ✓（心电、影像、镜检）、病灶 ✓（甲状腺超声，H06 测试）。**不能用一份肺部样例代表全类别**——本清单逐类别登记。

## 二、失败情形覆盖

| 情形 | 样例/测试 |
| --- | --- |
| 未登记指标 | h12_unknown_metrics.csv → 待映射队列（不丢弃、不自动解释）；`test_unknown_metric_sample_queues_without_dropping` |
| 未登记定性值 | h12_urine_stool.csv 便潜血"弱阳性" → unregistered_qualitative |
| 单位无换算依据 | tests/tabular_parsing（肌酐 mg/dL 逆向不换算，保留原单位） |
| **缺失单位（#19 P1）** | `feat/tabular-parsing` @ `b31a1e6` 新增 `unit_missing`；本分支待合并，已在 `test_full_chain.py` 显式标注不复用旧语义 |
| 数值无法解析 | tests/tabular_parsing（原值保留 + 逐项错误） |
| 表头不识别 / 空列 / 坏 Excel | tests/tabular_parsing + test_excel |
| 参考区间缺失 | tests/cross_system（no_reference，不编造阈值）；`test_real_csv_file_parses_and_queues_unmapped` 断言无法计算项原因可见 |
| **倒置/布尔/非有限参考区间** | `tests/exam_dictionary/test_catalog.py`（`aa2062be`，本分支已吸收） |
| 决策日期之后的记录 | tests/cross_system（显式排除并留痕） |
| 未识别版式 / 扫描件 / 无 OCR 引擎 | tests/report_extraction（显式失败状态）；`test_scanned_pdf_without_engine_is_explicitly_incomplete`、`test_unknown_layout_is_reported_not_guessed` |
| 跨部位关联 | tests/lesion（算法不自动匹配 + 人工关联拒绝） |
| 引用不存在的证据 | tests/llm（引用摘除并提示人工核对） |
| 草稿规则默认不启用 | tests/rule_candidates（draft 默认排除） |
| 冲突组优先级 | tests/rule_candidates（更高优先级胜出，落败规则依据移除）；本分支待合并 |
| 年龄未知时的年龄限定规则 | tests/rule_candidates（缺年龄→待确认，不推荐）；本分支待合并 |

## 三、H→T→前端链路联调（本次补充）

`test_full_chain.py` 覆盖 PR #29 审核要求的"实际 CSV/Excel/PDF→校对→分析→候选→方案"链路：

1. **文件 → 解析**：真实 CSV/Excel/PDF 三种入口在测试内实际生成并解析，非夹具字典直接喂入。
2. **解析 → 校对队列**：`to_proofread_queue()` 输出每条的 `computable` 与显式 `reason`，**无法计算项必须带原因进入页面**（C03 校对界面消费者），不允许静默丢弃。
   - 断言：`test_proofread_queue_separates_computable_from_not`、`test_uncomputable_items_are_visible_not_silently_dropped`。
3. **校对 → 分析**：`build_observations()` + `with_reference()` 演示 T04 编排层对接；`as_of` 决策日期由 T04 固定并传递；运行版本记录 `cross-system-summary-v1`。
4. **分析 → 候选**：`findings_from_abnormalities()` 演示 H05 异常 + H02 关联 → `NormalizedFinding`；`RuleCandidateService` 输出直接供 plan_builder 消费；`REVIEW_REQUIRED` 状态与 `rule_set_version="rule-content-v1"` 显式传递。
5. **候选 → 方案**：构造 `PlanBuildRequest`（`BudgetSpec(limit_cents=500_000, currency="CNY")`）走通三档方案产出，并断言**方案内每条建议可回溯到原始 `record_ref`**（`test_plan_items_trace_back_to_candidate_evidence`）。
6. **确定性**：同输入两次执行产出完全一致（`test_full_chain_is_deterministic_end_to_end`）。
7. **locator 保留**：Excel/PDF 的行号、页码在链路中不丢失（`test_proofread_locator_preserved_for_traceback`）。
8. **待复核与冲突可见**：`test_plan_keeps_requires_review_and_reports_conflicts`、`test_missing_info_and_excluded_reach_the_page`。

与 T 系列的具体对接约定（沿用）：

- **T03 导入**：CSV/Excel 行来自 T03 文件解析（编码探测/大小限制归 T03）；`ParsedTabularReport` 的 `entries/issues/unmapped` 对接 C03 候选、错误、待映射三区展示。
- **T04 分析编排**：`Observation` 映射与 `as_of` 传递见上。
- **T05 候选汇总**：同一检查多问题只计一次已在服务内去重。
- **T10 问答**：`QAContext` 证据条目 ref_id 使用 `record_ref`，保证引用可回溯（引用校验与 H08 共用 `app/llm/citations.py`）。

## 四、覆盖状态

- [x] 第二节全部 9 类别有明确标注的自制样例或既有 demo（基础信息/问卷与体格检查类文字条目经 h12 样例 + exam_catalog 覆盖；影像类经 h12_thyroid_us.txt 与 H06 测试覆盖）
- [x] 数值 / 定性 / 文字 / 病灶四种形态均有可运行样例与测试
- [x] 失败情形（解析失败、未知项、单位无依据、版式不识别、引用不存在等）均有测试
- [x] **实际 CSV/Excel/PDF 文件 → 校对 → 分析 → 候选 → 方案的整体联调**（`test_full_chain.py`）
- [x] **无法计算项带显式原因传至页面**（校对队列 `computable` + `reason`）
- [x] main 已合并的 #11 修正已吸收并与 main 逐字节一致
- [ ] **本分支所含 H 模块的阻断项修复（#19/#20/#21/#23/#24/#26）合并进 main** —— 待各自分支合并后重跑本套件
- [ ] 普通新建档案的端到端浏览器流程（M4 共同验收，依赖 C/T 系列）
- [ ] 真实机构版式样例（待本机构报告适配任务）

## 五、验证记录

执行环境：`backend` 目录，Python 3.12 venv。

```
$ python -m pytest tests -q
439 passed, 4 skipped in 25.42s
```

子系统：

| 目录/文件 | 结果 |
| --- | --- |
| `tests/integration_h12/`（合计） | **57 passed, 1 skipped** |
| ├─ `test_sample_chain.py` | 10 passed |
| ├─ `test_full_chain.py` | 14 passed |
| └─ `test_service_contracts.py` | 33 passed, 1 skipped |
| `tests/exam_dictionary/` | 29 passed（含已吸收的 `aa2062be` 参考区间边界回归） |

### 契约一致性检查结果

`test_service_contracts.py` 对照 `docs/H_SERIES_SERVICE_CONTRACTS.md` 核对结论：

- **版本号全部一致**：`exam-dictionary-v1`、`finding-catalog-v1`、`tabular-parsing-v1`、`report-extraction-v1`、`report-structuring-v1`、`cross-system-summary-v1`、`imaging-report-parser-v1`、`rule-candidates-v1`、`qa-service-v1`、`model-task-registry-v1`。
  说明：实现把版本号放在**类属性 `VERSION`**（非实例属性 `version`），文档描述用 `version: str`；语义一致，此处按实现核对并记录该形态差异。
- **硬性规则通过**：H02 `relation_type` 仅取提示/观察/危险因素，无确诊口径；H11 映射模板 14 条全部 `unverified`；H09 未接入任务均给出显式 `unavailable_reason`（`artifact_missing` / `review_not_frozen`）；H07 规则内容 `pending_review` 起步。
- **已记录的两处命名差异（不构成阻断，供 T 系列对齐）**：
  1. 契约写 `LesionTerminologyConfig`，实现为 `LesionSiteConfig`（同义：部位词表配置）。
  2. 契约写字典加载器 `ExamDictionary.lookup` 等为实例方法，实现一致；但文档中 `version` 字段应改注为 `VERSION` 类属性以与实际形态对齐。
- **本分支未合并项**：H06 的 `SECTION_KEYS` 由 PR #23 修复（`565d45b`）引入，本分支为未合并状态，测试**显式 skip 并标注来源**，不假装通过。

> 契约文档与实现的这些措辞差异属**文档待更新**，将在 #23 合并后随 H12 重新合并 main 时一并修订。
