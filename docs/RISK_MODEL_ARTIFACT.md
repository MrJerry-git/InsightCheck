# 风险模型制品与加载契约

负责人：王宏锦。日期：2026-09-18。实现：`backend/app/ml/risk/`。

状态：**适配器与契约已实现并用合成制品验证；尚无真实数据训练结果，未接入 API，也不是临床模型。** 与 [离线风险基线程序](RISK_EXPERIMENTS.md) 的分工是：拟合留在离线程序，在线请求只加载可信制品并推理。

## 任务定义前提

模型卡的 `task_kind` 必须二选一，取值只能来自枚举：

| 取值 | 含义 |
| --- | --- |
| `same_round_finding_classification` | 当次（同轮）异常分类 |
| `future_event_prediction` | 未来事件预测 |

当前公开数据只能支持前者；后者因随访、删失与资料可获得时间未定而保持 BLOCKED。决定依据见 [公开数据候选对照](DATA_CANDIDATES.md#任务定义决定)。

`review_status` 沿用任务卡的 `DRAFT / BLOCKED / FROZEN`。**只有 `FROZEN` 允许在线推理**；未冻结时训练与推理都返回 `review_not_frozen`，不会用程序填审核记录。合成工程夹具可以冻结（与离线 `TaskSpec` 的 `synthetic` 用法一致），但制品始终带合成警告。

## 制品目录

```text
artifact-001/
├── model_card.json     # 模型定义：输入、输出、适用范围、版本与限制
├── metadata.json       # ModelArtifactMetadata（版本与创建时间）
└── pipeline.joblib     # 预处理 + 模型的 sklearn Pipeline，仅用于本机可信来源
```

- `model_card.json` 记录 `artifact_sha256`，加载时逐个文件校验；哈希不符按 `artifact_invalid` 拒绝，绝不静默加载。
- 加载时同时校验 `pipeline` 的 `feature_names_in_` 与模型卡的 `required_features` 一致，防止制品与卡片版本漂移。
- `joblib` 使用反序列化加载，因此**只加载本机可信制品**，不加载来历不明的模型文件。
- 保存时若目标目录已有 `pipeline.joblib` 则拒绝覆盖，保留上一次制品。
- 合成测试制品可以保存和加载，但必须保留 `is_synthetic=true` 与合成警告。

## 模型卡字段

| 字段 | 作用 |
| --- | --- |
| `model_version` / `feature_pipeline_version` / `algorithm` | 制品与特征流水线版本；`algorithm` ∈ `logistic`、`random_forest`、`lightgbm`，与离线 `risk_baseline.estimators()` 的键一致（有测试守护） |
| `risk_code` | 输出语义代码，进入 `RiskPrediction.risk_code` |
| `task_kind` / `task_id` / `task_version` / `review_status` | 任务定义与审核状态；未冻结不得推理 |
| `outcome_definition` / `negative_definition` / `availability_assumptions` / `review_record` | 直接取自已冻结的任务卡，不由程序推断 |
| `data_source_kind` / `is_synthetic` | `synthetic`、`public_observational`、`partner_observational`；两者必须一致 |
| `validation_kind` | `internal_random_split`、`temporal_holdout`、`external_site`。内部随机划分**不是**外部验证，会带对应警告 |
| `calibrated` / `clinical_use` | v1 固定 `calibrated=false`、`clinical_use=false`（传 `true` 直接被校验拒绝） |
| `forbidden_features` | 与 `required_features` 不得相交；`subject_id`、`label` 永远禁止 |
| `required_features` | 每项含 `name`、`source`、`unit`、`missing_policy`、`review_status` |
| `applicable_populations` / `population_definition` / `limitations` | 适用范围与使用限制，必须显式声明 |
| `training_dataset_version` / `training_dataset_sha256` / `data_manifest_sha256` / `training_split_sha256` | 数据、清单与患者级划分的可追溯哈希；内部划分必须记录划分清单哈希 |
| `code_commit` / `code_dirty` / `dependencies` | 代码提交、工作区是否干净、依赖版本 |
| `trained_at_iso` / `artifact_sha256` | 由 `save()` 写入 |

## 输入契约

服务层用 `RiskPredictionRequest` 提交：

| 字段 | 说明 |
| --- | --- |
| `subject_id` | 必填 |
| `features` | 只接受模型卡声明的字段；**多一个字段也拒绝**（`feature_set_mismatch`），不静默丢弃 |
| `feature_pipeline_version` | 必须与制品一致，否则 `feature_version_mismatch` |
| `population` | 必填；不属于 `applicable_populations` 时 `population_not_applicable`。未声明人群不能视为适用 |
| `trace_id` / `evidence_refs` | 追溯字段，原样回填到输出 |

数值校验：布尔与非数值文本按 `feature_not_numeric` 拒绝，`±Inf` 同样拒绝。`None` 与 `NaN` 都是缺失标记，只有该字段声明 `missing_policy=train_median_impute` 时才允许，并交由制品内已拟合的中位数填补处理；声明 `reject` 时按 `feature_missing` 拒绝。

适配器**不补齐、不猜测、不重新划分受检者、不生成标签**，也不做临床阈值判断。

## 输出契约

`assess()` 返回 `RiskAssessment`：

| 字段 | 说明 |
| --- | --- |
| `status` | `available` 或 `unavailable` |
| `prediction` | 仅在 `available` 时存在；`RiskPrediction` 含 `probability`、`risk_model_version`、`feature_pipeline_version`、`risk_code`、`trace_id`、`evidence_refs` |
| `reason` / `detail` | 仅在 `unavailable` 时存在，给出机器可读原因与人类可读说明 |
| `warnings` | 由模型卡派生，见下表 |

模型校验保证二者互斥：可用时不得带原因码，不可用时不得带概率。**制品缺失、特征不符、版本不符或人群不适用时返回明确不可用状态，不回退为虚构概率，也不用 0 或 0.5 占位。**

`RiskModel.predict()` 受既有抽象接口签名限制无法返回状态，因此它在不可用时抛出携带 `reason` 的 `RiskModelUnavailableError`。服务层应使用 `assess()`；`load_risk_model()` 返回可用性摘要且不抛异常，`require_risk_model()` 在不可用时抛异常。

### 不可用原因

| 原因码 | 触发条件 |
| --- | --- |
| `artifact_missing` | 制品目录或必需文件不存在 |
| `artifact_invalid` | 模型卡/元数据非法、制品哈希不符、无法反序列化、流水线与卡片特征不一致、输出不是概率 |
| `dependency_unavailable` | 未安装 `research` 可选依赖（pandas、scikit-learn、lightgbm、joblib） |
| `model_not_loaded` | 适配器尚未加载或训练制品 |
| `review_not_frozen` | 任务审核状态不是 `FROZEN` |
| `feature_missing` | 缺少必需字段，或该字段声明拒绝缺失却没有值（`None` 或 `NaN`） |
| `feature_not_numeric` | 布尔、非数值文本、`±Inf` |
| `feature_set_mismatch` | 出现未声明字段 |
| `feature_version_mismatch` | 请求的特征流水线版本与制品不一致 |
| `population_not_applicable` | 请求人群不在制品声明范围内 |

### 警告

| 警告 | 含义 |
| --- | --- |
| `no_clinical_use` | v1 制品一律不是临床模型 |
| `synthetic_artifact_engineering_only` | 合成制品，仅用于工程验证 |
| `internal_split_is_not_external_validation` | 内部随机划分不得称为外部验证 |
| `uncalibrated_probability` | 概率未校准，不得作为临床阈值使用 |
| `code_commit_was_not_clean` | 离线运行记录了脏工作区 |

## 离线到在线：固化流程

1. 先用既有离线程序跑完实验（需要已冻结任务卡、队列文件与清单）：

   ```powershell
   .venv/Scripts/python.exe -m app.research.risk_baseline --task ../data/processed/task.json --data ../data/processed/cohort.parquet --manifest ../data/processed/manifest.json --output ../artifacts/risk/run-001
   ```

2. 人工填写注册信息，把完成目录固化成在线制品：

   ```python
   from pathlib import Path

   from app.ml.risk import (
       BaselineExperimentRegistration,
       BaselineRiskAdapter,
       RiskFeatureSpec,
       RiskTaskKind,
   )

   adapter, metadata = BaselineRiskAdapter.from_baseline_experiment(
       Path("../artifacts/risk/run-001"),
       BaselineExperimentRegistration(
           algorithm="lightgbm",
           risk_code="<输出语义代码>",
           task_kind=RiskTaskKind.SAME_ROUND_FINDING,
           feature_pipeline_version="<特征流水线版本>",
           population_definition="<人群定义>",
           applicable_populations=("<人群标识>",),
           limitations=("<使用限制>",),
           required_features=(
               RiskFeatureSpec(
                   name="<字段名>",
                   source="<来源>",
                   unit="<单位>",
                   review_status="reviewed",
               ),
           ),
       ),
   )
   adapter.save(Path("../artifacts/risk/artifact-001"), metadata)
   ```

   `from_baseline_experiment()` 会校验：报告存在、任务 `status == FROZEN`、所选基线文件存在、声明字段与任务卡 `features` **完全一致**；不一致时分别返回 `artifact_missing`、`review_not_frozen` 或 `feature_set_mismatch`。模型卡中的任务定义、可用性假设与审核记录全部来自报告，不由程序编造；离线运行若记录了脏工作区，会追加一条使用限制。

3. 在线只加载制品并推理：

   ```python
   from pathlib import Path

   from app.ml.risk import RiskPredictionRequest, load_risk_model

   loaded = load_risk_model(Path("../artifacts/risk/artifact-001"))
   if not loaded.available:
       raise RuntimeError(loaded.availability.reason)  # 不回退为虚构概率

   assessment = loaded.model.assess(
       RiskPredictionRequest(
           subject_id="<受检者>",
           features={"<字段名>": 1.0},
           feature_pipeline_version="<特征流水线版本>",
           population="<人群标识>",
           trace_id="<追溯标识>",
       )
   )
   if assessment.status.value == "available":
       prediction = assessment.prediction
       print(prediction.probability, prediction.risk_model_version)
   else:
       print(assessment.reason, assessment.detail)
   ```

## 安全与边界

1. 不绕过任务检查：未冻结任务不能训练、不能注册、不能推理；不能通过填写审核字段解除状态。
2. 不重新划分受检者：患者级划分由离线程序保留，适配器只消费划分好的数据，`metadata` 中显式记录该约定。
3. 不把内部随机划分称为外部验证，不宣称跨数据集或前瞻性有效性。
4. 合成制品保留合成标签与警告，不与真实数据混用。
5. 不在 API 路由或 `workflow_models.py` 中直接替换现有实现；接入由负责人在契约评审后完成。
6. 不实现 DeepFM 真实交互训练，也不声称已有真实推荐标签。

## 验证

自动化测试覆盖：算法枚举与离线基线键一致；模型卡拒绝 `clinical_use=true`、来源/合成标志不一致、禁用特征与缺失划分哈希；合成与内部划分警告保留；保存再加载后预测一致；制品缺失、制品被篡改、缺少特征、多出特征、非数值、布尔、`±Inf`、特征版本不符、人群不适用时返回明确原因且**不返回概率**；`None` 与 `NaN` 按缺失策略处理并可被中位数填补；可用结果携带完整版本与追溯字段并可序列化；未冻结状态阻断训练与推理；未知标签、额外字段、缺失字段、单一类别与非数值训练数据被拒绝；拒绝覆盖已有制品；`from_baseline_experiment` 从真实离线基线报告固化制品，并拒绝未冻结或字段不符的实验。测试文件：`backend/tests/risk/test_artifact.py`（本次 29 项全部通过，含 Logistic 与 LightGBM 两种算法）。

2026-09-18 验证：完整后端测试 182 项通过，其中本分支新增 41 项；`ruff check app tests` 通过。全部拟合都使用合成工程夹具，**没有真实数据训练结果，也没有接入 API**。运行环境为 Windows + Python 3.12，pandas 2.3.3、scikit-learn 1.8.0、lightgbm 4.6.0、torch 2.12.0+cpu；测试里出现的 `joblib` NumPy 2.5 弃用提示与 LightGBM 特征名提示在既有 `tests/test_research.py` 中同样存在，属上游环境提示，不影响本次结果。
