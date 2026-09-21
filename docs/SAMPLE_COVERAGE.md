# 自制样例与内容覆盖清单（H12）

负责人：王宏锦（WHJ-2007）。日期：2026-09-21。状态：自制工程样例（文件内标注"自制样例"或作为测试夹具使用），**不是真实体检数据**，不用于任何医学有效性结论。

样例位置：`backend/tests/fixtures/h12_samples/`。联调链路测试：`backend/tests/integration_h12/test_sample_chain.py`（样例 → H03 解析（H01 字典映射）→ H05 跨系统汇总 → H02 关联 → H07 规则候选）。

本分支（feat/sample-coverage-suite）已按合并提交集成 H01—H11 全部功能分支：exam-dictionary（H01/H02）、tabular-parsing（H03）、report-extraction（H04）、cross-system-analysis（H05）、imaging-lesion-multisite（H06）、rule-candidates（H07）、llm-qa-service（H08）、model-task-registry（H09）、reusable-components（H10）、jiuhua-data-prep（H11）；下方覆盖矩阵引用的各系列测试均可在本分支直接运行。

## 一、样例清单与覆盖矩阵

| 样例文件 | 类别（任务书第二节） | 值形态 | 覆盖点 | 验证测试 |
| --- | --- | --- | --- | --- |
| h12_blood_routine.csv | 血常规 | 数值 | 白细胞/红细胞/血红蛋白/血小板/MCV/中性粒细胞比率；6 项全部命中字典编码 | `test_blood_routine_sample_parses_fully_mapped` |
| h12_urine_stool.csv | 尿液与粪便检查 | 定性 + 文字 | 尿蛋白"±"（登记允许值）、便潜血"弱阳性"（**未登记值→保留原文入队**）、尿/便镜检文字透传 | `test_urine_stool_sample_covers_qualitative_and_text` |
| h12_biochemistry_lipids.csv | 肝肾生化 + 糖代谢血脂 | 数值 | 13 项生化血脂；"偏高"提示列保留（report_flag）；参考区间前缀（<、≥）原样保留不猜测 | `test_biochemistry_sample_flags_abnormalities_from_report_hint` |
| h12_unknown_metrics.csv | 扩展项目（未登记） | 数值 + 文字 | 未知指标（D-二聚体、超敏CRP）→ 待映射队列，不丢弃；机构自定义文字条目 | `test_unknown_metric_sample_queues_without_dropping` |
| h12_ecg_report.txt | 心电图及功能检查 | 文字结论 | 心电图所见/诊断段落；进汇总做时间线对照，不做异常判定 | `test_text_samples_feed_summarizer_without_judgment` |
| h12_thyroid_us.txt | 超声/放射影像报告 | 文字 + 病灶描述 | 甲状腺超声所见/提示；病灶句候选由 H06 解析（`tests/lesion/test_multisite_and_revisions.py`） | `test_text_samples_feed_summarizer_without_judgment` |

形态覆盖核对：数值 ✓（血常规、生化）、定性 ✓（尿便）、文字 ✓（心电、影像、镜检）、病灶 ✓（甲状腺超声，H06 测试）。**不能用一份肺部样例代表全类别**——本清单逐类别登记。

## 二、失败情形覆盖

| 情形 | 样例/测试 |
| --- | --- |
| 未登记指标 | h12_unknown_metrics.csv → 待映射队列（不丢弃、不自动解释） |
| 未登记定性值 | h12_urine_stool.csv 便潜血"弱阳性" → unregistered_qualitative |
| 单位无换算依据 | tests/tabular_parsing（肌酐 mg/dL 逆向不换算，保留原单位） |
| 数值无法解析 | tests/tabular_parsing（原值保留 + 逐项错误） |
| 表头不识别 / 空列 / 坏 Excel | tests/tabular_parsing + test_excel |
| 参考区间缺失 | tests/cross_system（no_reference，不编造阈值） |
| 决策日期之后的记录 | tests/cross_system（显式排除并留痕） |
| 未识别版式 / 扫描件 / 无 OCR 引擎 | tests/report_extraction（显式失败状态） |
| 跨部位关联 | tests/lesion（算法不自动匹配 + 人工关联拒绝） |
| 引用不存在的证据 | tests/llm（引用摘除并提示人工核对） |
| 草稿规则默认不启用 | tests/rule_candidates（draft 默认排除） |

## 三、与 T 系列的联调对接说明

1. **T04 分析编排**：`build_observations()`（integration_h12/test_sample_chain.py）演示解析结果 → `Observation` 的映射方式；`as_of` 决策日期由 T04 固定并传递；分析运行版本记录 `cross-system-summary-v1`。
2. **T05 候选汇总**：`findings_from_abnormalities()` 演示 H05 异常清单 + H02 关联 → `NormalizedFinding`；`RuleCandidateService` 输出直接供三档方案（plan_builder）消费；同一检查多问题只计一次已在服务内去重。
3. **T10 问答**：`QAContext` 由 T04/T05 产出的结构化发现与方案快照构造（见 `app/llm/qa.py`）；证据条目 ref_id 建议使用 `record_ref`，保证问答引用可回溯到记录。
4. **T03 导入**：CSV/Excel 行来自 T03 的文件解析（编码探测/大小限制归 T03）；解析输出 `ParsedTabularReport` 的 `entries/issues/unmapped` 分别对接校对界面（C03）的候选、错误与待映射队列展示。

## 四、覆盖状态

- [x] 第二节全部 9 类别有明确标注的自制样例或既有 demo（基础信息/问卷与体格检查类文字条目经 h12 样例 + exam_catalog 覆盖；影像类经 h12_thyroid_us.txt 与 H06 测试覆盖）
- [x] 数值 / 定性 / 文字 / 病灶四种形态均有可运行样例与测试
- [x] 失败情形（解析失败、未知项、单位无依据、版式不识别、引用不存在等）均有测试
- [x] 与 T04/T05/T10 的联调对接样例代码
- [ ] 普通新建档案的端到端浏览器流程（M4 共同验收，依赖 C/T 系列）
- [ ] 真实机构版式样例（待本机构报告适配任务）
