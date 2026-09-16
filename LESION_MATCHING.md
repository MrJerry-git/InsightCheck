# 纵向影像病灶匹配与变化分析

## 1. 范围与安全边界

第三阶段只处理已经结构化的影像报告病灶，不读取 CT 图片，不训练影像模型，也不输出疾病诊断。输入病灶至少应带有检查日期和病灶类型；器官、检查部位、位置、尺寸和分级允许缺失，但缺失会降低可匹配证据。

病灶匹配是辅助归轨：`MATCHED` 才能自动关联既有轨迹；`NEED_REVIEW` 只保留候选关系，`matched_track_id` 必须为空；`NEW_LESION` 不进入既有轨迹。低置信度结果不得静默当作同一病灶。

## 2. 模块结构

```text
backend/app/features/lesion/
├── terminology.py  # 病灶类型、器官、检查部位和位置术语统一
├── scorer.py       # 单个当前病灶 × 既有轨迹的可解释评分
├── matcher.py      # 批次级一对一分配、阈值决策和轨迹存在状态
├── trend.py        # 已归轨观察的描述性变化特征
└── schemas.py      # 输入、输出、配置和状态契约
```

API 只处理 HTTP 契约，`LesionAnalysisService` 编排 Feature，Repository 仅负责读取结构化 Demo 观察。

## 3. 术语统一

当前版本 `lesion-terminology-v2` 至少支持：

| 原始术语 | 规范术语 |
| --- | --- |
| `右上肺`、`右肺上叶`、`RUL` | `RIGHT_UPPER_LOBE` |
| `右下肺`、`右肺下叶`、`RLL` | `RIGHT_LOWER_LOBE` |
| `肺结节`、`PULMONARY_NODULE`、Demo 肺结节代码 | `PULMONARY_NODULE` |
| `肺`、`右肺`、`左肺`、`LUNG` | `LUNG` |
| `胸部`、`CHEST` | `CHEST` |

术语相同只说明表达被统一，不自动证明两个观察属于同一病灶。

## 4. 配置化评分

默认配置位于 `LesionMatchingConfig`，权重和阈值不散落在匹配逻辑中：

| 评分项 | 默认权重 | 满分条件 |
| --- | ---: | --- |
| 病灶类型 | 0.35 | 规范病灶类型一致 |
| 器官/检查部位 | 0.20 | 规范器官一致；器官缺失时比较检查部位 |
| 位置 | 0.20 | 规范解剖区域一致 |
| 尺寸连续性 | 0.15 | 相对尺寸变化越小得分越高 |
| 分级 | 0.10 | 两侧分级均存在且一致 |

权重之和必须为 1。输出同时返回每项 `component_scores`、`weighted_contributions` 和中文 `reasons`。

时间间隔和既有轨迹的处理方式：

- 每个候选轨迹使用日期最近的历史观察进行比较；
- 输出明确记录使用的轨迹及距上次检查月数；
- 超过配置的支持间隔时乘以 `long_interval_multiplier`；
- 尺寸剧烈变化、位置冲突或位置缺失会应用配置化置信度上限，禁止自动确认。

## 5. 阈值与一对一约束

默认阈值：

```text
confidence >= 0.80       → MATCHED
0.55 <= confidence < 0.80 → NEED_REVIEW
confidence < 0.55        → NEW_LESION
```

同一检查批次先计算全部“当前病灶 × 历史轨迹”候选分数，再按置信度执行一对一分配。一个历史轨迹最多分配给一个当前病灶，一个当前病灶最多分配一个历史轨迹。最佳候选已被另一病灶占用时，剩余病灶按 `NEW_LESION` 输出，并给出“一对多错配保护”原因。

`NEED_REVIEW` 的 `candidate_track_id` 可指向待审核轨迹，但 `matched_track_id` 必须为空。其轨迹存在状态为 `UNRESOLVED`，不会被自动标成延续或消失。

## 6. 消失与未决

历史轨迹在下一批次没有匹配结果时：

- 同一检查范围明确完整、时间间隔位于配置范围内：`DISAPPEARED`；
- 检查范围不完整、时间间隔过长或存在待审核候选：`UNRESOLVED`；
- 存在自动匹配观察：`CONTINUING`。

这里的 `DISAPPEARED` 是结构化报告层面的“本次未再记录”，不是医学上的确定消失结论。

## 7. 变化特征

趋势分析只接收已经归入同一轨迹的结构化观察，按检查日期排序：

- `absolute_size_change = last_size - first_size`，单位 mm；
- `relative_size_change = absolute_size_change / first_size`；
- `growth_rate = absolute_size_change / elapsed_years`，单位 mm/年；
- `grade_change`：`UNCHANGED / INCREASED / DECREASED / CHANGED / UNKNOWN`；
- `continuous_occurrences`：截至最近一次观察、相邻间隔未超过配置上限的连续次数；
- `months_since_last_exam`：评估日期到最近观察的月数；
- `new_lesion`、`disappeared`、`stable`、`growing`、`shrinking` 为结构化描述性标志。

稳定、增大和缩小使用 `LesionTrendConfig` 的绝对与相对变化阈值；这些标志描述数据变化，不表示疾病性质或诊断。

## 8. API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/v1/lesion-analysis/match` | 批次级可解释一对一匹配 |
| `POST` | `/api/v1/lesion-analysis/trend` | 计算单条轨迹变化特征 |
| `GET` | `/api/v1/lesion-analysis/demo` | 从数据库读取四年 Demo 并实时执行匹配与趋势计算 |

所有评分请求都可携带 `config` 覆盖默认权重和阈值；配置会进行范围、阈值顺序和权重总和校验。

## 9. Demo 数据

执行：

```powershell
cd backend
python -m alembic upgrade head
python -m app.seed
```

会创建匿名患者 `DEMO-LESION-PATIENT-001` 和轨迹 `DEMO-LONGITUDINAL-LESION-001`：

| 年份 | 尺寸 | 分级 | 标记 |
| --- | ---: | --- | --- |
| 2023 | 5.0 mm | G1 | DEMO DATA |
| 2024 | 5.3 mm | G1 | DEMO DATA |
| 2025 | 5.8 mm | G2 | DEMO DATA |
| 2026 | 6.2 mm | G2 | DEMO DATA |

所有体检批次均为 `is_demo=true`。前端 `/imaging` 从 Demo API 加载数据，展示时间轴、ECharts 尺寸趋势、分级变化、匹配置信度和 NEED_REVIEW 保护提示。数值由后端算法返回，不在页面中写死。

## 10. 当前限制

- 术语字典只覆盖当前演示和测试范围，需要后续由医学专家治理扩展；
- 尺寸只处理单一 `size_mm`，尚未支持长短径、体积和测量误差模型；
- 一对一分配采用确定性置信度优先策略，尚未引入全局最优匹配算法；
- 分级顺序依赖配置，未知分级只返回 `CHANGED`，不会猜测严重程度；
- 不从报告自由文本抽取病灶，不读取 CT 图片，不训练影像模型。

> 本系统基于历史体检数据提供健康趋势分析与体检项目辅助推荐，不构成疾病诊断、医疗处方或治疗建议，最终体检方案应由具有资质的医务人员结合实际情况确认。
