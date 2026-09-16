# 循影定检数据字典

## 1. 适用范围与约定

本文档描述第二阶段数据库字段。开发环境使用 SQLite，字段设计保持 PostgreSQL 可迁移性。本阶段仅实现数据结构、基础维护、指标标准化和病灶术语映射；不训练模型，不生成风险、推荐或 AI 结果。

所有表都包含以下公共字段：

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `id` | string(36) | 是 | 记录主键 | UUID 字符串，不承载业务语义 | 仅作引用与追溯，不直接作特征 |
| `created_at` | datetime(tz) | 是 | 记录创建时间 | 数据库生成 | 仅审计，不默认作特征 |

“参与未来模型”只说明预期用途，不代表模型已实现或字段必然入模。JSON 证据引用将在后续阶段制定稳定引用契约。

## 2. Patient（受检者）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `anonymous_code` | string(64) | 是 | 受检者匿名业务编码 | 去首尾空白并大写；唯一 | 仅关联与分组，不直接作特征 |
| `gender` | enum | 是 | 性别：`female/male/other/unknown` | 缺省为 `unknown` | 可作为经治理的人群特征/规则上下文 |
| `birth_date` | date | 否 | 出生日期 | 不保存身份证来推导；允许缺失 | 可派生检查时年龄，不直接传原日期给模型 |
| `height` | float | 否 | 身高，单位 cm | `0 < height <= 300` | 可参与经版本化特征计算 |

隐私硬边界：本实体不包含且系统不得保存身份证、手机号、住址。

## 3. HealthCheck（体检批次）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `patient_id` | FK | 是 | 所属受检者 | 引用 `Patient.id` | 纵向分组键，不直接作特征 |
| `check_date` | date | 是 | 体检日期 | ISO 日期 | 纵向窗口和时间间隔特征 |
| `institution` | string(200) | 否 | 体检机构名称 | 当前仅去协议层长度校验，后续可接机构字典 | 默认不直接入模，可用于数据来源校验 |
| `is_demo` | boolean | 是 | 是否为合成演示批次 | 默认 `false`；Demo 必须为 `true` | 训练/评估时必须用于排除 Demo 数据 |

## 4. MetricDictionary（指标字典）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `metric_code` | string(64) | 是 | 指标稳定编码，如 `ALT` | 去空白、大写；唯一 | 特征身份键 |
| `canonical_name` | string(200) | 是 | 指标规范中文名称 | 非空 | 解释与追溯 |
| `aliases` | JSON list[string] | 是 | 原始名称别名集合 | 与编码、规范名共同参与无空白/不区分大小写匹配 | 输入标准化，不直接入模 |
| `standard_unit` | string(50) | 否 | 统一后的单位 | 无单位指标可为空 | 决定特征数值口径 |
| `category` | string(100) | 是 | 指标分类 | 非空 | 可作分组元数据，不默认入模 |
| `unit_conversions` | JSON object | 是 | 原单位到标准单位的仿射换算参数 | 每项为 `factor`、`offset`；只执行字典明确配置的转换 | 保证数值特征同口径 |
| `valid_min` | float | 否 | 基础有效值下界 | 与 `valid_max` 同时存在时不得大于上界 | 输入质量控制，不是诊断阈值 |
| `valid_max` | float | 否 | 基础有效值上界 | 同上 | 输入质量控制，不是诊断阈值 |
| `source` | string(200) | 是 | 字典依据或维护来源 | 非空 | 可追溯元数据 |
| `version` | string(64) | 是 | 字典版本 | 非空 | 特征复现实验依据 |

## 5. LabMetric（实验室指标观测）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `health_check_id` | FK | 是 | 所属体检批次 | 引用 `HealthCheck.id` | 纵向时间锚点 |
| `metric_code` | FK/string(64) | 是 | 标准指标编码 | 必须存在于指标字典 | 特征身份键 |
| `original_name` | string(200) | 是 | 来源中的原指标名称 | 原样保留 | 追溯，不入模 |
| `canonical_name` | string(200) | 是 | 标准指标名称快照 | 由匹配到的指标字典产生 | 解释，不直接入模 |
| `original_value` | string(100) | 是 | 来源中的原始值 | 原样保留，避免失败时丢失证据 | 追溯，不直接入模 |
| `value` | float | 否 | 换算后的标准数值 | 仅在可解析、单位受支持时形成 | 未来纵向数值特征 |
| `original_unit` | string(50) | 否 | 来源单位 | 原样保留 | 质量与追溯 |
| `standard_unit` | string(50) | 否 | 标准单位快照 | 来自指标字典 | 特征口径元数据 |
| `reference_min` | float | 否 | 已换算的参考下限 | 使用同一单位换算；不得大于上限 | 可生成相对参考范围特征 |
| `reference_max` | float | 否 | 已换算的参考上限 | 同上 | 可生成相对参考范围特征 |
| `status` | enum | 是 | `normal/low/high/unknown` | 仅依据本条参考上下限比较；不是疾病诊断 | 可作为类别特征候选 |
| `normalization_status` | enum | 是 | 标准化处理结果 | `normalized/unmapped_metric/invalid_value/unsupported_unit/implausible_value/invalid_reference` | 数据质量筛选依据 |
| `normalization_version` | string(64) | 是 | 标准化器版本 | 当前为 `metric-normalizer-v1` | 特征复现实验依据 |

## 6. ImagingExam（影像检查）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `health_check_id` | FK | 是 | 所属体检批次 | 引用 `HealthCheck.id` | 纵向关联键 |
| `exam_type` | string(100) | 是 | 影像检查类型 | 本阶段只存规范代码/文本，不做推断 | 未来影像特征分组 |
| `body_part` | string(100) | 是 | 检查部位 | 本阶段只存规范代码/文本 | 未来影像特征分组 |
| `report_text` | text | 否 | 原始影像报告文本 | 原文保留；不得直接交给 LLM 决定推荐 | 仅经授权的结构化抽取来源，不直接入模 |
| `exam_date` | date | 是 | 实际检查日期 | ISO 日期 | 病灶纵向时间锚点 |

## 7. Lesion（单次病灶观测）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `imaging_exam_id` | FK | 是 | 来源影像检查 | 引用 `ImagingExam.id` | 证据关联键 |
| `lesion_type` | string(100) | 是 | 病灶类型 | 本阶段不做复杂医学术语推断 | 未来病灶类别特征 |
| `original_location` | string(200) | 是 | 来源中的病灶部位表述 | 原样保留 | 追溯，不直接入模 |
| `location` | string(100) | 是 | 规范病灶部位 | `右上肺/右肺上叶/RUL → RIGHT_UPPER_LOBE` | 未来匹配与位置特征 |
| `size_mm` | float | 否 | 单次病灶尺寸，mm | 非负 | 未来纵向变化特征 |
| `grade` | string(100) | 否 | 来源记录的分级 | 不补猜、不诊断 | 未来经治理类别特征候选 |
| `description` | text | 否 | 病灶描述 | 来源/演示说明；不自动升级为诊断 | 结构化抽取证据，不直接入模 |

## 8. LesionTrack（病灶轨迹）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `patient_id` | FK | 是 | 所属受检者 | 引用 `Patient.id` | 纵向分组键 |
| `canonical_lesion_id` | string(100) | 是 | 跨期病灶稳定业务标识 | 唯一；不得由本阶段术语映射自动生成 | 轨迹身份键 |
| `lesion_type` | string(100) | 是 | 轨迹病灶类型 | 不补猜 | 未来轨迹类别特征 |
| `location` | string(100) | 是 | 轨迹规范部位 | 使用病灶术语代码 | 未来匹配与位置特征 |
| `first_seen` | date | 是 | 最早观察日期 | 不得晚于 `last_seen` | 未来持续时间特征 |
| `last_seen` | date | 是 | 最近观察日期 | 不得早于 `first_seen` | 未来新近性特征 |

## 9. LesionObservation（病灶轨迹观察）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `lesion_track_id` | FK | 是 | 所属病灶轨迹 | 引用 `LesionTrack.id` | 轨迹分组键 |
| `lesion_id` | FK | 是 | 被关联的单次病灶 | 引用 `Lesion.id`；每个病灶最多进入一个轨迹观察 | 证据关联键 |
| `exam_date` | date | 是 | 观察日期 | 与来源检查日期保持一致 | 纵向排序键 |
| `size_mm` | float | 否 | 轨迹观察时的尺寸快照 | 非负 | 未来变化率特征 |
| `grade` | string(100) | 否 | 轨迹观察时的分级快照 | 不补猜 | 未来类别变化特征候选 |
| `match_confidence` | float | 是 | 关联置信度 | `[0,1]`；Demo 人工关联为 `1.0` | 未来匹配质量筛选，不作为健康风险本身 |
| `match_status` | enum | 是 | `candidate/manual_confirmed/rejected/unmatched` | 本阶段 Seed 仅使用 `manual_confirmed`，没有匹配算法 | 决定轨迹能否进入未来特征 |

## 10. ExamItem（体检项目目录）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `code` | string(64) | 是 | 项目稳定编码 | 去空白、大写；唯一 | DeepFM 项目身份键（未来） |
| `name` | string(200) | 是 | 项目名称 | 非空 | 推荐解释 |
| `category` | string(100) | 是 | 项目类别 | 非空 | 未来项目侧特征与规则上下文 |
| `description` | text | 否 | 项目说明 | Demo 条目显式含 `DEMO DATA` | 解释，不默认入模 |
| `radiation` | boolean | 是 | 是否涉及辐射 | 默认 `false` | 未来安全规则上下文 |
| `cost_level` | enum | 是 | `low/medium/high` | 枚举 | 未来方案约束与项目侧特征 |
| `recommended_interval_months` | integer | 否 | 目录建议间隔（月） | 正整数；本阶段 Demo 不填医学间隔 | 未来规则上下文，不能单独决定推荐 |

## 11. ExamHistory（已检项目）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `health_check_id` | FK | 是 | 所属体检批次 | 与 `exam_item_id` 组合唯一 | 患者历史行为锚点 |
| `exam_item_id` | FK | 是 | 实际执行的体检项目 | 引用 `ExamItem.id` | DeepFM 交互数据候选（未来，须排除 Demo） |
| `result_status` | enum | 是 | `completed/normal/abnormal/inconclusive/unknown` | 不把状态升级为疾病诊断 | 未来经治理类别特征候选 |

## 12. MedicalRule（医疗规则）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `rule_code` | string(100) | 是 | 规则稳定编码 | 与版本组合唯一 | 不入模；规则追踪键 |
| `rule_type` | string(100) | 是 | 规则分类 | 非空 | 规则编排元数据 |
| `exam_item_id` | FK | 否 | 规则作用的具体项目 | 为空表示非单项目范围；后续规则引擎解释 | 不入模 |
| `condition_json` | JSON object | 是 | 结构化触发条件 | 本阶段仅存储，不执行复杂规则 | 不入模；未来规则输入定义 |
| `action` | enum | 是 | `include/exclude/adjust_score/require_review` | 枚举 | 修改未来模型排序，但不是模型特征 |
| `priority` | integer | 是 | 规则优先级 | 非负 | 未来冲突处理依据 |
| `source` | string(300) | 是 | 规则依据来源 | 必须明确，不得编造 | 审计与解释 |
| `version` | string(64) | 是 | 规则版本 | 与 `rule_code` 组合唯一 | 推荐复现依据 |
| `enabled` | boolean | 是 | 是否启用 | 默认 `true` | 规则执行过滤条件 |

本阶段不 Seed 医疗规则，避免将未经确认的医学逻辑伪装成已实现规则。

## 13. RiskPrediction（风险预测结果容器）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `patient_id` | FK | 是 | 预测对象 | 引用 `Patient.id` | 输出关联 |
| `as_of_health_check_id` | FK | 否 | 预测所截至的体检批次 | 删除批次时置空，证据引用仍需保留 | 输出时间锚点 |
| `risk_code` | string(100) | 是 | 风险类别编码 | 后续由风险任务字典定义 | 模型输出类别 |
| `probability` | float | 是 | 风险概率 | `[0,1]`；不得包装成确定诊断 | LightGBM 输出（未来） |
| `risk_level` | string(50) | 否 | 经校准规则定义的展示等级 | 本阶段不定义阈值 | 展示派生值 |
| `feature_pipeline_version` | string(64) | 是 | 特征流水线版本 | 非空 | 复现实验 |
| `risk_model_version` | string(64) | 是 | 风险模型版本 | 非空 | 复现实验 |
| `evidence_refs` | JSON list[object] | 是 | 输入证据引用 | 默认空列表，未来需稳定契约 | 可解释追溯 |
| `trace_id` | string(100) | 是 | 单次推理运行标识 | 非空 | 运行追溯 |
| `is_demo` | boolean | 是 | 是否为 Demo 输出 | 默认 `false` | 训练/评估排除标识 |

## 14. Recommendation（体检方案结果容器）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `patient_id` | FK | 是 | 方案对象 | 引用 `Patient.id` | 输出关联 |
| `as_of_health_check_id` | FK | 否 | 方案使用的数据截止批次 | 删除批次时置空 | 输出时间锚点 |
| `plan_tier` | enum | 是 | `simplified/standard/deep` | 枚举 | 方案分档 |
| `status` | enum | 是 | `draft/review/confirmed` | 默认 `draft` | 人工确认流程状态 |
| `feature_pipeline_version` | string(64) | 否 | 特征流水线版本 | 有模型流程时填写 | 复现依据 |
| `risk_model_version` | string(64) | 否 | 风险模型版本 | 有风险输入时填写 | 复现依据 |
| `recommendation_model_version` | string(64) | 否 | 推荐模型版本 | 有 DeepFM 排序时填写 | 复现依据 |
| `rule_version` | string(64) | 否 | 规则集版本 | 执行规则时填写 | 复现依据 |
| `trace_id` | string(100) | 是 | 单次推荐流程标识 | 非空 | 运行追溯 |
| `is_demo` | boolean | 是 | 是否为 Demo 输出 | 默认 `false` | 真实结果隔离 |

## 15. RecommendationItem（方案项目）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `recommendation_id` | FK | 是 | 所属方案 | 与 `exam_item_id` 组合唯一 | 输出关联 |
| `exam_item_id` | FK | 是 | 候选体检项目 | 引用 `ExamItem.id` | 项目身份 |
| `model_score` | float | 否 | 规则处理前的模型匹配分 | `[0,1]` | DeepFM 输出（未来） |
| `final_score` | float | 否 | 规则处理后的最终排序分 | `[0,1]` | 最终排序依据（未来） |
| `decision` | enum | 是 | `include/exclude/require_review` | 枚举 | 最终结构化决定 |
| `rank` | integer | 否 | 方案内排序 | 正整数 | 展示排序 |
| `explanation` | text | 否 | 结构化原因的可读说明 | 不替代证据字段 | 展示 |
| `evidence_refs` | JSON list[object] | 是 | 支持该项目决定的历史证据 | 默认空列表 | 可解释追溯 |
| `applied_rules` | JSON list[object] | 是 | 修改模型排序的规则决定 | 默认空列表，需含规则代码与版本 | 规则追溯 |

## 16. AIReport（AI 解释报告）

| 字段 | 类型 | 必填 | 业务含义 | 标准化/约束 | 未来模型参与 |
| --- | --- | --- | --- | --- | --- |
| `patient_id` | FK | 是 | 报告对象 | 引用 `Patient.id` | 不入 ML |
| `recommendation_id` | FK | 否 | 所解释的方案 | 删除方案时置空 | 不入 ML |
| `report_type` | enum | 是 | `health_summary/recommendation_explanation/chat_summary` | 枚举 | LLM 任务类型 |
| `content` | text | 是 | LLM 生成的自然语言内容 | 只解释结构化结果，不拥有推荐权 | 不入 ML |
| `llm_model` | string(100) | 是 | 使用的语言模型 | 非空 | LLM 追溯 |
| `prompt_version` | string(64) | 是 | 提示模板版本 | 非空 | LLM 复现依据 |
| `source_trace_id` | string(100) | 是 | 结构化来源流程标识 | 非空 | 输入追溯 |
| `is_demo` | boolean | 是 | 是否为 Demo 输出 | 默认 `false` | 真实结果隔离 |

## 17. 当前标准化规则

- 指标名先做 Unicode NFKC、去首尾和内部空白、英文大写，再匹配 `metric_code`、`canonical_name` 和 `aliases`。
- 单位只按指标字典中显式配置的 `factor` 与 `offset` 转换；未知单位不猜测，结果标记为 `unsupported_unit`。
- 非数值、NaN 和无穷值标记为 `invalid_value`；超出基础有效值边界标记为 `implausible_value`。基础有效值边界仅作数据质量校验，不是诊断阈值。
- 参考范围和观测值使用相同换算；参考下限大于上限标记为 `invalid_reference`。
- 病灶部位当前仅映射 `右上肺`、`右肺上叶`、`RUL` 到 `RIGHT_UPPER_LOBE`；未知术语返回未匹配，不补猜。
- 病灶术语映射不执行跨年匹配。Demo 轨迹观察为人工构造并标记 `manual_confirmed`。

> 本系统基于历史体检数据提供健康趋势分析与体检项目辅助推荐，不构成疾病诊断、医疗处方或治疗建议，最终体检方案应由具有资质的医务人员结合实际情况确认。
