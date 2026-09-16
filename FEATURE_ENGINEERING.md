# 历年体检指标纵向特征工程

## 1. 阶段范围

第四阶段只处理已经完成指标名称和单位标准化的结构化 `LabMetric` 观测，将其转换为可解释的纵向指标特征和机器学习可消费的数值字典。本阶段不训练 LightGBM，不生成风险概率，不实现推荐或医疗规则，也不将描述性趋势表述为疾病诊断。

功能入口是 `FeaturePipeline.build(PatientFeatureRequest) -> PatientFeatureVector`。流水线是无数据库、无网络、无机器学习框架依赖的纯计算模块；Repository 或 Service 在后续阶段负责把 SQLAlchemy 实体映射成 `MetricObservation`，Feature 层不反向依赖数据库。

## 2. 输入契约

每条 `MetricObservation` 至少包含：

| 字段 | 含义 |
| --- | --- |
| `source_id` | 原始 `LabMetric` 或导入记录的证据引用 |
| `metric_code` | 已标准化的稳定指标编码，流水线统一为大写 |
| `canonical_name` | 规范指标名称 |
| `observed_at` | 观测日期，回归使用实际日期间隔 |
| `value` | 标准单位下的值；允许缺失 |
| `reference_min` / `reference_max` | 当次观测适用的参考范围；允许缺失 |
| `status` | 标准化后的 `normal` / `low` / `high` / `unknown` |
| `category` / `feature_group` | 系统级特征分组依据，显式分组优先 |

`PatientFeatureRequest.as_of_date` 可固定特征截止日期。晚于该日期的观测不会参与计算，也不会进入 `evidence_refs`，避免未来数据泄漏。

## 3. 单指标特征定义

数值缺失的观测保留在来源计数和证据引用中，但不参与统计计算。有效观测按日期排序。

| 特征 | 定义 |
| --- | --- |
| `current_value` | 截止日最近一次有效值 |
| `previous_value` | 当前值之前最近一次有效值 |
| `absolute_change` | `current_value - previous_value` |
| `relative_change` | `absolute_change / abs(previous_value)`；前值为 0 时为 `null` |
| `mean` | 全部有效历史值的算术平均 |
| `std` | 全部有效历史值的总体标准差（`ddof=0`）；单次记录为 0 |
| `min` / `max` | 全部有效历史值的最小值与最大值 |
| `slope` | 以首次观测为时间原点、实际间隔折算成年后的普通最小二乘斜率，单位为“标准单位/年” |
| `trend` | `UNKNOWN` / `RISING` / `FALLING` / `STABLE` / `FLUCTUATING` |
| `abnormal_count` | 状态为高/低，或超出当次参考范围的有效观测次数 |
| `consecutive_abnormal_count` | 从最近来源观测向前连续异常的次数；缺失或正常记录会中断连续性 |
| `distance_to_reference_upper` | 最近有效值距当次参考上限的有符号距离；超上限时为负 |
| `distance_to_reference_lower` | 最近有效值距当次参考下限的有符号距离；低于下限时为负 |
| `early_warning` | `NONE` 或 `EARLY_WARNING` |
| `warning_reason` | 预警成立时的可读证据说明，否则为 `null` |
| `observation_count` | 有效数值数量 |
| `source_observation_count` | 输入来源观测总数，包括缺失值 |
| `missing_observation_count` | 数值缺失数量 |
| `has_history` | 至少有两次有效数值时为 `true` |

流水线还保留 `first_to_last_relative_change`、`coefficient_of_variation`、`direction_consistency`、`trend_reason` 和 `evidence_refs`，用于解释趋势判定和追溯来源。

## 4. 趋势判定

趋势不由 `current_value - previous_value` 单独决定。`TrendEngine` 同时使用：

1. 所有有效观测按实际日期拟合的线性回归斜率；
2. 首次到末次的相对变化率；
3. 总体标准差相对于均值的波动系数；
4. 相邻非零变化与回归方向一致的比例；
5. 有效观测数量。

默认规则如下，全部阈值位于 `TrendConfig`，不得在业务代码中散落：

- 高波动且方向一致性不足时为 `FLUCTUATING`；
- 归一化斜率、首尾变化率和方向一致性共同支持正方向时为 `RISING`；
- 三项共同支持负方向时为 `FALLING`；
- 斜率、首尾变化和总体波动都位于稳定阈值内时为 `STABLE`；
- 其余三次及以上、方向反复的序列为 `FLUCTUATING`；
- 不足两次有效记录时不推断方向，返回 `UNKNOWN`、`slope=null`、`has_history=false`，并在原因中明确证据不足。

默认阈值：归一化斜率 `0.02`、首尾相对变化 `0.05`、波动系数 `0.15`、方向一致性 `0.75`。它们是工程初值，不是临床诊断界值；修改阈值必须提升 `feature_pipeline_version` 并重新验证。

## 5. Early Warning

`EARLY_WARNING` 是参考区间内的趋势提示，不是异常诊断。默认必须同时满足：

- 至少三次有效观测；
- 最近连续观测保持同一变化方向；
- 相邻有效观测间隔不超过 18 个月；
- 参与连续段的值都仍在各自适用参考区间内；
- 到同一侧参考界限的距离逐次严格缩小；
- 最近距离不超过当次参考区间宽度的 15%。

上升序列检查参考上限，下降序列检查参考下限。参考范围缺失、记录间隔过大、方向反转、已经越界或接近程度不足时不产生预警。预警结果必须同时返回 `warning_reason`，说明连续次数、接近方向和当前距离。

## 6. 缺失与短序列语义

- 单次记录：完整返回当前值和静态统计，`has_history=false`，方向性字段可为空，不报错。
- 两次记录：计算变化、回归斜率和方向，但不触发需要三次记录的 Early Warning。
- 中间年份缺失：回归按真实日期间隔计算，不把缺失年份插值为观测；年度空档超过连续性阈值会阻止 Early Warning。
- 值缺失：保留来源和缺失计数，排除出数值统计；最新来源值缺失时，`current_value` 仍取最近有效值。
- 全部值缺失：数值统计返回 `null`，计数和证据仍可追溯，不抛出异常。

流水线不做插值或医学意义上的缺失填补。未来训练阶段如需填补，必须作为模型预处理的一部分单独版本化，不能静默改变这里的可解释原始特征。

## 7. 系统级特征与模型向量

每个指标优先使用显式 `feature_group`；否则按配置化类别别名归入以下对象：

- `metabolic_features`
- `cardiovascular_features`
- `liver_features`
- `kidney_features`
- `other_features`

每组保留指标明细、指标数量、当前异常指标数量和 Early Warning 指标数量。

`PatientFeatureVector.feature_values` 是只包含 `float`、`int`、`bool` 或 `null` 的扁平字典，特征名格式为：

```text
{feature_group}__{metric_code}__{feature_name}
```

例如 `liver__ALT__slope`。分类趋势另以 `trend_code` 表示：`FALLING=-1`、`STABLE=0`、`RISING=1`、`FLUCTUATING=2`；`UNKNOWN` 使用 `null`，避免把证据不足伪装成有方向的类别。`feature_order` 明确记录本次字典的稳定排列，`feature_pipeline_version` 当前为 `metric-feature-pipeline-v1.1`。

同一请求无论输入顺序如何都会产生相同特征顺序。不同患者可能拥有不同指标集合；未来 LightGBM 训练阶段必须基于已登记的指标目录固定训练列集合，并按列名对齐缺失特征，同时保存该列契约和流水线版本。本阶段不伪造这一尚未形成的训练 Schema。

## 8. 可追溯性与安全边界

- 每个指标特征保存参与计算的全部 `source_id`；患者向量汇总去重后的 `evidence_refs`。
- 每个趋势保存 `trend_reason`，每个预警保存 `warning_reason`。
- 输出保存 `feature_pipeline_version`；参数、分组或公式发生语义变化时必须升级版本。
- 本模块只描述历史数值变化，不输出疾病结论、风险概率或体检项目推荐。
- 不读取身份证、手机号、住址，也不向 LLM 发送原始体检报告。

## 9. 测试覆盖

接口级测试覆盖多年上升、下降、稳定和波动序列；验证最近一次变化不能覆盖多年趋势；覆盖参考区间内的上界预警；覆盖单次、两次、中间年度缺失、数值缺失、全缺失、连续异常、系统分组、截止日期防泄漏、空输入，以及输入顺序无关的扁平特征顺序。
