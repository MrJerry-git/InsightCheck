# H 系列解析/分析/模型服务契约（M0 初稿）

负责人：王宏锦（WHJ-2007）。日期：2026-09-20。状态：接口设计初稿，对应 `TEAM_TASKS_V2.md` 第八节 M0 中"解析/分析服务契约及目录初稿"。本文只描述将要提供的模块与函数签名约定，**不代表功能已实现**；实现随 H01—H12 各任务分支交付。

阅读对象：王天一（T04/T05/T08/T10 集成）、陈子正（C03/C04/C05/C06/C07/C11 页面对齐）。

## 一、通用约定

1. H 系列服务全部是**纯计算模块**（同 `app/features/`、`app/rules/`、`app/ml/` 现有模式）：不直接访问数据库、不持有会话。持久化字段由王宏锦在第十节提出，由王天一落地迁移（T02/T08）；服务配置由王宏锦提出，王天一接入全局配置（`app/core/config.py`）。
2. 每个服务输出携带版本号（形如 `exam-dictionary-v1`）。修改输出结构时递增次版本，消费方按版本判断兼容性。
3. 显式状态优先：映射失败、参考区间缺失、无法比较、模型未接入都必须返回明确状态枚举，不回退为默认值或虚构数据（沿用 `CONTEXT.md` 不变量）。
4. 原始值保留：所有解析输出同时保留原文与标准化结果，字段命名沿用 `LabMetric` 的 `original_*` / canonical 约定。
5. 内容文件（字典、关联、规则、模板）是 JSON，存放在对应模块 `data/` 目录，每条记录带 `source`、`source_version`、`review_status`。`review_status` 取值：`pending_review`（未经医学审核）/ `reviewed`。当前一律为 `pending_review`，不宣称医学审核通过。
6. 所有列表输出使用确定性排序（显式 sort key），保证同输入同输出。

## 二、H01 体检字典目录服务（新模块 `app/exam_dictionary/`）

内容文件：`app/exam_dictionary/data/exam_catalog.json`（首批目录），`data/packages/`（机构套餐配置，版本化）。

```python
@dataclass(frozen=True)
class ReferenceRange:
    population: str          # 适用条件描述，如 "成人男性"、"成人空腹"
    min_value: float | None
    max_value: float | None
    unit: str
    source: str              # 出处，如 "WS/T 405-2012"
    source_version: str
    review_status: str

@dataclass(frozen=True)
class CatalogEntry:
    code: str                # 稳定编码，优先 LOINC，无 LOINC 用前缀约定（见第四节）
    display_name: str
    aliases: tuple[str, ...] # 中文名/英文名/常见简称
    category: str            # 第二节类别，如 "blood_routine"
    system: str              # 归属系统，如 "hematology"
    value_type: str          # "numeric" | "qualitative" | "text" | "structured"
    standard_unit: str | None        # 定性/文字类为 None
    unit_conversions: tuple[...],    # 仿射换算 (factor, offset)，仅有依据时登记
    reference_ranges: tuple[ReferenceRange, ...]
    source: str
    source_version: str
    review_status: str       # 目录条目本身的审核状态
    status: str              # "active" | "pending_mapping"（待映射队列）

class ExamDictionary:
    version: str                                  # "exam-dictionary-v1"
    def lookup(self, raw_name: str) -> CatalogEntry | None
    def lookup_by_code(self, code: str) -> CatalogEntry | None
    def entries_by_category(self, category: str) -> list[CatalogEntry]
    def register_unknown(self, raw_name: str, context: str) -> UnmappedMetric
    # UnmappedMetric 进入待映射队列，不丢弃、不自动解释
```

加载器在 import 时校验 JSON 与 schema 一致（编码唯一、别名不与其它条目冲突、数值类必须有标准单位）。

**对 C11 的含义**：字典映射管理页可基于 `lookup` / `register_unknown` 的数据展示；对 T08 的含义：目录条目可直接序列化为管理 API 响应（`as_dict()`）。

## 三、H02 检查—发现—健康问题/疾病关联目录（同模块内容文件）

内容文件：`app/exam_dictionary/data/finding_associations.json`。

```python
@dataclass(frozen=True)
class FindingAssociation:
    association_id: str
    exam_code: str            # 关联的检查/指标编码（H01 code）
    condition_code: str       # 健康问题/疾病编码（ICD-10 或内部前缀编码）
    condition_name: str
    relation_type: str        # "abnormality_suggests"（异常提示，非确诊）
                              # "finding_observation"（发现需要观察）
                              # "risk_factor"（危险因素）
    direction: str            # "high" | "low" | "any" | "qualitative_positive" ...
    evidence_note: str        # 关联依据的通俗说明
    source: str
    source_version: str
    review_status: str

class FindingCatalog:
    version: str                                  # "finding-catalog-v1"
    def associations_for_exam(self, exam_code: str) -> list[FindingAssociation]
    def conditions_for_exam(self, exam_code: str, direction: str) -> list[FindingAssociation]
```

硬性规则：`relation_type` 只能取"提示/观察/危险因素"类值，目录层不表达"确诊"；C07 页面必须与已知诊断分开呈现（文案口径见 `TEAM_TASKS_V2.md` 第二节）。

## 四、H03 表格解析服务（新模块 `app/tabular_parsing/`）

```python
class TabularReportParser:
    version: str                                   # "tabular-parsing-v1"
    def parse(
        self,
        source_name: str,                          # 文件名，用于错误定位
        rows: list[dict[str, str]],                # CSV/Excel 已解出的行（键为表头）
        dictionary: ExamDictionary,                # H01 提供别名映射
    ) -> ParsedTabularReport

@dataclass
class ParsedMetricEntry:
    raw_name: str; raw_value: str; raw_unit: str | None
    page_hint: str | None                          # 原文位置（如有）
    row_index: int; column_name: str
    canonical_code: str | None                     # 未映射时为 None
    value_type: str                                # numeric/qualitative/text
    canonical_value: str | None                    # 数值（换算前原值另存）
    canonical_unit: str | None
    qualitative_status: str | None                 # 阴性/阳性/+/- 等归一
    text_value: str | None
    conversion_basis: str | None                   # 单位换算依据，未换算为 None
    status: str                                    # "mapped" | "unmapped" | "invalid_value" ...

@dataclass
class ParsedTabularReport:
    entries: list[ParsedMetricEntry]               # 确定性排序
    issues: list[ParseIssue]                       # 逐行逐列错误（source_name/row/column/field/message）
    unmapped: list[UnmappedMetric]                 # 未知项队列
```

规则：原值永远保留；单位换算必须命中 `unit_conversions` 中登记的依据，否则保留原单位并标记 `unit_unconverted`；定性结果按字典登记的允许值归一，未登记的保留原文并进待映射队列；文字结果原样透传。CSV 读取由 T03 负责（编码/分隔符探测属于文件管理），本服务只吃已解出的 `rows`；Excel 解析提供 `read_excel_rows(content: bytes) -> list[dict[str, str]]` 辅助函数（openpyxl，仅读值不读样式）。

## 五、H04 报告文本抽取服务（新模块 `app/report_extraction/`）

```python
class ReportTextExtractor:
    version: str                                   # "report-extraction-v1"
    def extract(self, source_name: str, content: bytes, suffix: str) -> ExtractedDocument
    # ExtractedDocument: pages -> lines（每行带 page_no / line_no / text 原文定位）
    # .txt 直接解码；.pdf 走文本层抽取（pypdf）；图片走 OCR 适配器（见下）
    # 扫描版 PDF / 无文本层：返回显式状态 "needs_ocr"，不返回空文本冒充成功

class OcrEngine(Protocol):
    def is_available(self) -> bool: ...
    def recognize(self, images: list[bytes]) -> list[str]: ...
# 内置 adapter：RapidOCR（可选安装，未安装时 is_available()=False 并给出安装说明）
# 引擎选择由配置注入（王天一接入 settings），缺省无引擎时显式不可用

class ReportStructurer:
    version: str                                   # "report-structuring-v1"
    def structure(self, document: ExtractedDocument) -> StructuredReport
    # 识别"项目/结果/单位/参考区间/提示"行与"所见/结论"段落，产出候选字段
    # 每个候选字段携带原文定位（page_no/line_no/raw_text），供 C03 校对
    # 支持版式清单与版本：data/supported_layouts.json，未识别版式显式返回 "unknown_layout"
```

支持版式在 `app/report_extraction/data/supported_layouts.json` 登记（版式说明 + 样例特征 + 版本），未列入的版式显式失败。图片 OCR 的实际运行证据记录在 H10 组件清单，未安装引擎不阻塞文本层 PDF 与手工校对路径。

## 六、H05 跨系统趋势及异常整理（新模块 `app/cross_system/`）

```python
class CrossSystemSummarizer:
    version: str                                   # "cross-system-summary-v1"
    def summarize(self, observations: list[SystemObservation]) -> CrossSystemSummary

# SystemObservation：metric_code / value_type / value / unit / reference(min,max,source,condition) / date / category / system / raw_ref
# 输出 CrossSystemSummary 按 类别/系统 分组：
#   numeric:     复用 app/features/trend_engine.py 的 TrendEngine 输出趋势方向，
#                附参考区间来源与适用条件；单位或适用条件变化 → "incomparable" 标记，不强行比较
#   qualitative: 状态时间线（日期 + 归一状态 + 原文）
#   text:        按日期排列的结论对照
#   abnormality: 异常清单，逐条引用当次参考区间（min/max/source/condition），无区间则标 "no_reference"
```

不编造通用阈值：无登记参考区间的指标不做异常判定，只做数值罗列。不产出未来数据。

## 七、H06 影像报告解析与多部位病灶匹配（扩展 `app/features/lesion/` + `app/report_extraction/`）

1. 影像报告字段解析（`app/report_extraction/imaging.py`）：从报告文本抽取 `部位 / 检查类型 / 所见 / 结论 / 病灶描述句`，产出候选结构，携带原文定位；解析失败保留原文。
2. 多部位术语（`features/lesion/terminology.py` 扩展）：术语表改为**配置注入**（`LesionTerminologyConfig`），内置肺部词表保持向后兼容，新增部位（甲状腺、肝、胆、肾、乳腺等）通过配置登记；跨部位**永不**强制关联（匹配仅在 同部位+同检查类型 内进行）。
3. 人工修订回算（`features/lesion/revisions.py` 新增）：输入人工判定（关联/解除/待定）+ 历史修订记录，重算轨迹状态；人工判定优先于算法匹配，每次回算生成新的修订条目（revision_no 递增、不覆盖历史）。
4. 不声称原始 CT/MRI 诊断：仅处理已结构化的报告文字与病灶描述，边界沿用 `LESION_MATCHING.md`。

## 八、H07 规则内容与候选生成服务（新模块 `app/rule_candidates/`）

内容文件：`app/rule_candidates/data/rule_content.json`（首批规则集）。

```python
@dataclass(frozen=True)
class RuleContentItem:
    rule_code: str; version: str
    priority: int                  # 确定性排序主键
    condition: dict                # 适用条件（类别/方向/人群），结构对齐 app/rules/models.py
    recommended_exam_codes: tuple[str, ...]
    reason_template: str           # 可解释理由
    missing_info_prompt: str | None
    source: str; source_version: str; review_status: str   # 一律 pending_review 起步

class RuleCandidateService:
    version: str                                   # "rule-candidates-v1"
    def candidates(self, findings: list[NormalizedFinding]) -> CandidateResult
    # NormalizedFinding 来自 H05 汇总；输出：
    #   candidates: 候选（去重：同一 exam_code 只保留优先级最高理由，附全部依据）
    #   missing_info: 缺失信息提示（无法判定时明确列出）
    #   excluded: 排除与冲突（同检查多问题只计一次、互相冲突的规则对）
```

排序确定性：`(priority, rule_code, version)` 三键稳定排序。本服务**不是** DeepFM 已接入：DeepFM 排序仍走 `app/ml/recommendation/` 既有制品链路；本服务在无模型时独立产生候选（`TEAM_TASKS_V2.md` 第六节硬性要求）。

## 九、H08 问答与结构化解释服务（扩展 `app/llm/`）

```python
class TemplatedLLMProvider(LLMProvider):   # 确定性模板实现，无外部依赖
class OpenAICompatibleLLMProvider(LLMProvider):
    # base_url / model / api_key 全部来自配置（环境变量注入，密钥不进 Git 与前端）
    # 超时、失败、限流显式报错；不降级为编造内容

class QAService:
    version: str                                   # "qa-service-v1"
    def answer(self, question: str, context: QAContext) -> QAAnswer
    # QAContext：当前档案记录（H05 汇总）、方案快照（plan_builder 只读视图）、
    #            可追溯依据（记录 id、参考区间来源、规则依据）
    # 引用守卫：答案中引用的记录 id 必须存在于 context，否则该引用标记 invalid
    # 只读保证：QAContext 不暴露任何写路径；答案不能修改方案（服务层无写接口）
```

`api_key` 未配置时 `is_available()=False`，调用方得到显式"模型问答不可用"，可回退 TemplatedLLMProvider（回退在响应中明确标注 `mode="template"`，不冒充真实模型）。

## 十、H09 模型任务注册与可替换适配器（新模块 `app/ml/tasks/`）

```python
@dataclass(frozen=True)
class ModelTaskRegistration:
    task_id: str                   # 如 "lung-cancer-future-event-nlst"
    disease_goal: str
    population: str                # 适用人群定义
    input_features: tuple[str, ...]
    time_horizon: str              # 预测窗口，如 "6-year"
    output_spec: str
    data_source: str               # synthetic / public_observational / partner_observational
    source_version: str
    status: str                    # "awaiting_data" | "in_development" | "integrated" | "retired"
    unavailable_reason: str | None # 对齐 RiskUnavailableReason 取值

class ModelTaskRegistry:
    version: str                                   # "model-task-registry-v1"
    def register(self, task: ModelTaskRegistration) -> None
    def get(self, task_id: str) -> ModelTaskRegistration | None
    def list_tasks(self) -> list[ModelTaskRegistration]     # 确定性排序
    def availability(self, task_id: str) -> TaskAvailability
    # TaskAvailability：available=False 时给出 reason，供 C07 显式展示"未接入"

class TaskModelAdapter(Protocol):
    # 可替换适配器：风险模型、排序模型各自一个槽位
    # 保留 LightGBM（风险）/ DeepFM（排序）接入路径；当前默认适配器返回显式不可用
```

首批注册内容：NLST 肺癌风险任务（对齐 `docs/RISK_TASK_NLST.md`，状态 `awaiting_data`）、DeepFM 排序任务（状态 `in_development`，指向既有制品链路）。

## 十一、H11 九华数据接入准备（新模块 `app/jiuhua_prep/`）

交付三件（均为模板与契约，不处理真实数据）：

1. `data/jiuhua_field_mapping_template.json`：源字段 → 目标实体/字段 的映射模板，每条带 `verification_status: "unverified"`；未登记字段进入待确认清单，不猜。
2. 质量摘要工具：对符合模板的样例文件输出逐字段计数/缺失率/取值分布，**标签与随访字段是否存在一律标 `to_be_verified`**。
3. 数据导出契约（`docs/JIUHUA_DATA_PREP.md`）：交付格式、匿名标识规则（uuid5 确定性 ID + 项目盐值，沿用 `ImportService` 模式）、批次溯源字段（对齐 `ImportBatch.source_dataset/source_kind/available_at`）、隐私硬边界。

## 十二、对 T 系列集成的存储字段提案（王宏锦 → 王天一）

以下为建议持久化的字段（**提案，不是迁移**；T02/T08 落地时可调整命名）：

| 用途 | 建议存储 | 消费方 |
| --- | --- | --- |
| 目录条目 | 扩展现有 `metric_dictionaries`：`value_type`、`system`、`display_name`；参考区间建议独立表 `reference_ranges`（metric_code、population、min/max、unit、source、source_version、review_status） | H03/H05、C04/C05、C11 |
| 待映射队列 | 表 `unmapped_metrics`（raw_name、context、首次出现批次、状态、resolved_code） | H01、C03、C11 |
| 检查—疾病关联 | 表 `finding_associations`（H02 字段原样） | H07、C07 |
| 跨系统分析运行 | 复用 T04 分析编排的运行记录，输入版本记 `cross-system-summary-v1` | T04、C04/C05 |
| 影像人工修订 | 表 `lesion_manual_revisions`（lesion_id、revision_no、action、actor、reason、created_at） | H06、C06 |
| 规则内容 | 复用现有 `medical_rules` 表（condition_json 对齐 RuleContentItem.condition） | H07、C08/C11 |
| 模型任务注册 | 表 `model_task_registrations` 或 T08 管理 API 内存注册表序列化 | H09、C07/C11 |
| 问答引用 | 随 T10 的问答持久化记录引用的记录 id 与上下文版本 | H08、C10 |

## 十三、与 C/T 任务的对接点汇总

| H 服务 | 主要消费方 | 对接内容 |
| --- | --- | --- |
| H01 字典 | T02/T03/T08、C03/C11 | 编码/别名/值类型/参考区间 |
| H02 关联 | T05、C07 | 异常 → 可能关联的健康问题（非确诊） |
| H03 表格解析 | T03 | 校对候选与逐项错误 |
| H04 报告抽取 | T03、C03 | 原文定位 + 结构候选 |
| H05 跨系统汇总 | T04、C04/C05/C07 | 按系统/类别的趋势、时间线、异常 |
| H06 影像与病灶 | T04、C06 | 报告字段、多部位匹配、人工修订回算 |
| H07 规则候选 | T05、C08 | 候选、理由、去重、缺失信息 |
| H08 问答 | T10、C10 | 引用可追溯的问答与解释 |
| H09 任务注册 | T08、C07/C11 | 模型可用性显式状态 |
| H11 九华准备 | T03/T08 | 字段映射模板、导出契约 |
