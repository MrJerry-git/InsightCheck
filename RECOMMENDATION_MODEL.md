# DeepFM 个性化体检项目匹配模型

## 1. 定位与边界

第六阶段预测的是 `Patient × ExamItem` 的匹配分数，不是疾病概率，也不是最终体检方案。固定流程为：

```text
高召回 Candidate Generator
→ DeepFM 匹配排序
→ 下一阶段 Rule Engine 安全筛选与排序修正
→ 医务人员确认
```

DeepFM 不执行复查间隔、辐射安全、年龄/性别禁忌、功能重复或资料不足规则。排名 API 明确返回 `safety_rules_applied=false` 和 `requires_rule_engine=true`。页面和后续解释层只能使用“匹配分数”或“推荐匹配度”，不得称为疾病概率。

当前仓库尚无第五阶段 LightGBM Adapter 和真实风险制品。Full DeepFM 已实现对带时间、模型版本的风险概率特征的真实消费，但专项训练仅使用 `is_demo=true` 的合成数据进行工程 smoke test，不产生或宣称真实离线效果。

## 2. 模块与接口

```text
app/ml/recommendation/
├── schemas.py              输入、训练、排名与版本契约
├── candidate_generator.py  高召回候选集合
├── encoding.py             类别 UNK、数值标准化与特征映射
├── network.py              FM + Deep PyTorch 网络
├── model.py                训练、排名、评估、保存与加载
├── metrics.py              Precision/Recall/NDCG @ K
└── baselines.py            Age/Gender 与外部 Rule 决定 baseline
```

外部模型缝隙是 `RecommendationModel` 的 `train / rank / evaluate / save / load`。业务编排由 `RecommendationRankingService` 完成，HTTP 层只处理协议和依赖注入。

## 3. 候选生成

`CandidateGenerator.generate(exam_items)` 对项目 ID 去重并返回稳定顺序的高召回集合。当前版本不按辐射、间隔、费用、年龄、性别或历史项目过滤，因此不会在 Rule Engine 之前静默删除安全敏感项目。

这一策略避免了模型层越权，但有以下限制：

- 候选完整性取决于上游 `ExamItem` 目录；目录缺项仍会漏掉必要项目；
- 全目录召回可能增加排序成本；
- 后续可以增加可解释的非安全召回策略，但必须测量候选 Recall，并保留全目录兜底；
- 任何安全过滤仍只能由 Rule Engine 执行。

候选生成版本当前为 `candidate-generator-v1`。

## 4. 输入特征

### Patient Features

- 人口学：年龄、性别；
- 历史项目：历史项目编码 one-hot、历史项目数量、未知历史编码数量；
- 当前指标：`current__*`；
- 纵向趋势：`trend__*`；
- 病灶变化：`lesion__*`；
- 风险概率：Full 模型中的 `risk__*`；
- 数据置信度；
- 当前候选项目距上次同项目的月份数；
- `feature_pipeline_version`、风险模型版本、证据引用和时间锚点。

### Exam Features

- `exam_code`；
- `category`；
- `body_part`；
- `radiation`；
- `cost_level`；
- `recommended_interval_months`。

患者 ID 不进入模型特征，防止模型仅记忆受检者身份。Full 模型中的风险概率与其他数值特征使用相同的标准化、线性项、FM embedding 和 Deep 网络路径，没有硬编码优先级或覆盖逻辑。风险消融实验使用同一实现的 `deepfm_without_risk` 变体，后者只移除 `risk__*` 字段。

## 5. 编码与冷启动

五个类别 field 分别是性别、项目编码、项目类别、部位和费用等级。每个 field 在训练时创建独立 `__UNK__` token：

- 未知 ExamItem 编码映射到项目编码 field 的 UNK；
- 未知类别、部位、费用分别映射到对应 field 的 UNK；
- 未知历史项目通过 `patient_unknown_history_count` 保留数量信息；
- 缺失数值按训练均值映射为标准化后的 0；
- 无年龄、未知性别、无项目历史的冷启动受检者可以正常评分。

模型不会为未知项目编造医学含义。新项目可以得到受控的泛化分数，仍需 Rule Engine 和人工确认。

## 6. DeepFM 结构

模型采用共享 feature embedding：

```text
Linear Component
+ FM 二阶交互 Component
+ Deep MLP Component
→ Sigmoid
→ 0~1 Patient × ExamItem 匹配分数
```

FM 项计算不同 field 的二阶交互，Deep 分支将全部 field embedding 展平后进入配置化 MLP。最终 sigmoid 仅约束匹配分数范围，不使其成为校准后的概率或疾病风险。

训练使用二元交叉熵与 Adam。随机种子、embedding 维度、隐藏层、dropout、训练轮数、批量大小、学习率和权重衰减均保存在配置中。

## 7. 时序与数据泄漏保护

每条训练样本必须满足：

- `label_observed_at > feature_as_of_date`；
- `history_latest_date <= feature_as_of_date`；
- `risk_as_of_date <= feature_as_of_date`；
- 存在风险特征时必须记录 `risk_model_version` 和 `risk_as_of_date`；
- 样本、患者和数据集的 `is_demo` 标记一致；
- 患者特征版本与训练数据集特征版本一致。

这些约束防止明确的日期穿越。对于字典内部是否混入未来数据，系统无法只从数值本身证明，数据生产流水线仍必须保存来源时间和证据引用，并在真实训练阶段执行按时间切分的独立审计。

## 8. 评估与 Baseline

统一输出：

- `Precision@5`、`Recall@5`、`NDCG@5`；
- `Precision@10`、`Recall@10`、`NDCG@10`。

项目数量少于 K 时，Precision 分母采用实际返回数量；无相关项目时 Recall 和 NDCG 为 0。指标公式已由手工例子验证。

四类可执行实验实现：

| 实验 | 实现 |
| --- | --- |
| Age/Gender | 按年龄段、性别与项目统计的平滑历史阳性率，并支持相同 Top-K 评估 |
| Rule-only | 消费外部 Rule Engine 的可追溯决定进行排名；不在本模块定义医疗规则 |
| DeepFM without risk | 与 Full 相同网络和编码流程，仅移除风险字段 |
| Full DeepFM | 消费全部患者、项目和版本化风险特征 |

Demo smoke test 只能证明代码、指标和边界可执行，不能作为模型优于 baseline 的实验结论。真实比较必须使用时间外验证集，并报告样本构成、置信区间和数据版本。

## 9. 模型制品

`save()` 生成一个目录：

| 文件 | 内容 |
| --- | --- |
| `weights.pt` | PyTorch 权重 |
| `embedding_config.json` | 网络结构、训练参数、随机种子、模型变体和模型版本 |
| `feature_mapping.json` | 类别词表、UNK、数值字段、均值/标准差和历史项目映射 |
| `metadata.json` | 模型版本、特征版本、数据集版本、Demo 标记、训练时间和训练损失 |

加载使用 `weights_only=true`，并从保存的配置和映射重建完全相同的网络。相同输入在保存前后必须产生一致排序和分数。

服务通过 `RECOMMENDATION_ARTIFACT_PATH` 加载已验证制品。未配置制品时排名接口返回 HTTP 503，不生成随机或写死分数。

## 10. 排名 API

```text
POST /api/v1/recommendation-ranking/rank
```

响应项目包含：

- `exam_item_id`；
- `deepfm_score`；
- `model_version`；
- `feature_version`；
- `trace_id`。

响应还包含候选生成版本、Rule Engine 必需标记、匹配分数语义和统一医疗免责声明。API 不保存最终 `Recommendation`，因为安全规则尚未执行。

## 11. 标签偏差审计

历史 `ExamHistory` 只证明“曾经开具或执行过”，不等价于“医学上最需要”。标签可能复制以下偏差：

- 医生个人偏好和机构套餐；
- 地区、费用、设备可及性与保险覆盖；
- 不同人群接受检查机会不均；
- 既有过度检查或漏检模式；
- 只有已开项目能观察结果形成的选择偏差。

真实训练前必须定义标签窗口、负样本和删失逻辑；区分“未开具”和“明确不需要”；报告人群分层指标；尽可能引入专家复核标签、指南证据或反事实/倾向校正。当前代码不把历史开具行为描述为医学真值。

## 12. 6C 审计结果

| 审计项 | 结果 | 依据 |
| --- | --- | --- |
| Model Boundary Score | PASS（5/5） | 候选、模型、规则和最终方案职责分离；API 强制标记后续 Rule Engine |
| Metric Correctness | PASS | 手工 Precision/Recall/NDCG 例子与 Top-5/10 集成测试通过 |
| Cold Start Robustness | PASS | 未知患者历史、项目编码、类别和部位走受控 UNK，不越界 |
| Bias Awareness | PASS | 历史开具偏差、选择偏差和真实训练前治理要求已显式记录 |
| Architecture Alignment | PASS | API → Service → Candidate Generator/RecommendationModel；模型不访问数据库或执行规则 |

工程边界结论：`READY FOR STAGE 7`。这表示可以进入 Rule Engine 集成阶段，不表示 DeepFM 已具备生产医学有效性；真实数据、第五阶段风险制品和时间外实验仍是生产前置条件。
