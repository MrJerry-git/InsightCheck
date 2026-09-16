# 离线风险基线程序

新增 `app.research.risk_baseline` 提供 Logistic、随机森林和 LightGBM 的统一离线执行入口。**当前只用自动化合成夹具验证工程行为，没有 NLST 真实模型结果，也没有接入在线 RiskModel 服务。**

## 支持范围

- 每人一条样本，明确的 0/1 结局，经过任务卡允许的数值特征；未知标签拒绝训练。分类字段须经版本化特征构建转换，不能把类别编号直接当连续量。
- 按 subject_id 排序后，以固定随机种子 20260916 做 60%/20%/20% 分层划分；每人只在一个集合出现。重复测量会报错，后续需专门分组设计。
- 训练集学习中位数填补、缺失指示和缩放；验证/测试只变换。某特征在训练集全缺失时终止。
- 三个模型使用预先固定参数，不根据测试分数挑选胜者。阈值固定 0.5，仅供工程验证；尚未增加概率校准、调参或临床阈值选择。
- 输出 ROC-AUC、average precision（AP，不冒称梯形积分 PR-AUC）、Brier、F1、灵敏度、特异度、混淆矩阵、校准分箱和 200 次患者重采样的百分位区间。最少每类 10 人仅是程序划分条件，不证明统计样本量足够。
- 这是内部随机划分，不是时间外、外部或前瞻性验证；跨数据集有效性没有证据。

## 执行契约

先安装 `.[dev,research]`。`requirements-research-win-py312.lock.txt` 记录本机完整研究环境版本，属于 Windows Python 3.12 版本快照，不是带包哈希的跨平台锁文件。

任务 JSON 采用 `TaskSpec` 严格字段：task_id、version、status、source_kind、features、forbidden_features、outcome_definition、negative_definition、availability_assumptions、review_record、data_manifest_sha256、dataset_sha256。status 必须是 FROZEN，且清单及输入 Parquet 的实际 SHA256 必须匹配；程序不能替代任务审核。

数据文件列必须恰好为 `subject_id`、`label` 和 features 列，不接收多余结局字段；不自动从原始 NLST 表选列或生成标签。实际队列构建脚本将在任务冻结后实现。不要通过改状态或填虚假审核信息跳过未决条件。

以下是任务冻结后的命令格式，当前 NLST 任务不能直接执行：

```powershell
.venv/Scripts/python.exe -m app.research.risk_baseline --task ../data/processed/task.json --data ../data/processed/cohort.parquet --manifest ../data/processed/manifest.json --output ../artifacts/risk/run-001
```

制品目录包含三个模型的预处理与权重、任务规格、split 清单、预测明细和报告。报告记录数据/划分哈希、代码提交及工作区状态、依赖版本、随机种子和全部固定比较结果；输出目录已存在时拒绝覆盖。joblib 文件只用于可信本机制品，不加载来历不明的模型。

CLI 的文件哈希校验绑定本次输入快照；原始到队列转换的语义仍须独立审核。`run()` 是内部工程函数，合成测试可直接调用；正式实验使用 CLI。同一固定测试集重复查看后再改特征仍会构成泄漏，程序不能自动阻止研究者在不同输出目录中反复试验。

## 已验证与后续工作

自动化测试验证任务状态拒绝、重复受检者/未知标签/额外列/无限数拒绝、输入顺序不改变划分、训练集填补隔离、指标公式、三个模型保存后预测一致、输出防覆盖，以及审计报告不泄露样本标识。

2026-09-17 验证：完整后端测试 136 项通过（含 13 项研究测试），Ruff 通过；另核验本地公开文件均匹配固定 SHA256。测试客户端仍有两项上游弃用提示。本轮未改前端，不重复宣称新的前端验证。

后续：先完成真实任务与队列；再加入静态/纵向消融、开发集校准与阈值选择、时间条件验证和适用性判断；最后实现面向服务的 LightGBM Adapter。不能把此离线程序的存在当作已实现真实风险评估。
