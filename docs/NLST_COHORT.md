# NLST 受检者级适配入口

负责人：王宏锦。日期：2026-09-18。实现：`backend/app/research/nlst_cohort.py`。

本模块把已审计的 NLST 公开临床子集转换成**每位受检者一行**的特征表，并同时输出字段映射与质量摘要。它只做可复现的结构性转换，**不生成标签**。

选定候选的理由见 [公开数据候选对照](DATA_CANDIDATES.md)：NLST 公开子集是唯一在仓库内实际下载、校验并审计过的真实观察性数据。

## 复现步骤

在 `backend` 目录执行：

```powershell
.venv/Scripts/python.exe -m pip install -e '.[dev,research]'
.venv/Scripts/python.exe -m app.research.nlst_cohort ../data/raw/nlst --download --output ../data/processed/nlst/cohort-001
```

输入输出都在 Git 忽略目录（`data/`、`artifacts/`）：**原始数据、转换表、患者级划分、模型与预测结果都不进版本库**，只提交适配代码、字段映射与不含个体信息的质量报告。

固定版本与复现要求：

- 只读取 IDC v24 固定存储桶路径，逐个文件与 `app.research.nlst` 中记录的实测 SHA256 比对；不一致时失败并保留文件待复核，不自动接受新版本。
- 校验表内 `dataset_version`；不是 `2011.02.03/05.12.21` 时拒绝，要求先复核再使用。
- 输出目录已存在时拒绝覆盖，保留上一次结果。
- 不使用未经核验的镜像绕过申请或授权条件。

## 输出文件

| 文件 | 内容 | 是否可提交 |
| --- | --- | --- |
| `features.parquet` | 每位受检者一行的特征表，含 `subject_id` | 否（患者级数据，本地保留） |
| `field_mapping.json` | 全部输出列的来源、聚合、单位、语义核验状态与排除字段清单 | 可（无个体信息） |
| `quality.json` | 行数、覆盖度、缺失统计、文件哈希与限制说明 | 可（仅汇总，无个体信息） |

`quality.json` 的 `privacy` 字段与测试共同保证：只输出汇总计数，不含任何受检者标识或逐行记录。不含个体信息的实测副本见 [NLST 适配质量摘要](NLST_COHORT_QUALITY.json)。

## 本次实测（2026-09-18）

2026-09-18 按上述命令实际下载固定快照并运行两次，输出 53,452 位受检者 × 18 列。两次运行的 `features.parquet` 字节哈希、`field_mapping.json` 与 `quality.json`（除 `built_at` 时间戳外）完全一致，`features_sha256 = 9618bd52…c731`。

输出与既有审计逐项对齐，说明读取与聚合没有引入偏差：

| 本次输出 | 数值 | 对应审计值 |
| --- | ---: | --- |
| 受检者数 | 53,452 | `nlst_prsn` 53,452 |
| `ct_screen_rounds` = 1 / 2 / 3 | 1,351 / 1,519 / 23,583 | NLST 审计的 1 / 2 / 3 轮人数 |
| `screen_observed_t0/t1/t2` | 26,310 / 24,722 / 24,106 | `nlst_screen` 各轮 `study_yr` 行数 |
| `index_scr_days` 未知数 | 4,640 | `nlst_prsn.scr_days1` 缺失 4,640 |
| 比较阅片无法同轮关联行数（T1） | 9 | 全表 18 行的 T1 部分 |

实测还给出两个必须保留为未知的规模，不能当作阴性或 0：

- **3,477 位受检者**在 T1 有筛查记录但没有异常记录行（`screen_observed_t1` 24,722 对 `ab_number_t1_max` 有效 21,245）。"没有记录行"是否等于未见异常**尚未复核**，因此这几列在轮次观察标记之外保持未定。
- `ab_long_dia_t1_max` 只有 6,967 人有值：源字段单位与测量口径未复核，且绝大多数受检者没有直径记录，不能按 0 或毫米解读。

`age`、`gender`、`race`、`cigsmok` 的取值分布（27 / 2 / 11 / 2 个不同值）说明编码字典确实需要先复核，这也是它们只作为描述性列的原因。

## 字段映射

`role=descriptive` 的列只用于数据质量与覆盖审计，**不能直接进入模型特征**；`semantics=structure_only` 表示字段存在且类型已知，但其临床语义尚未在仓库内复核。

| 输出列 | 来源 | 聚合 | 单位 | 语义 | 用途 |
| --- | --- | --- | --- | --- | --- |
| `subject_id` | `nlst_prsn.pid` | 加队列前缀 `nlst-idc-v24:` | identifier | 已核验 | 主键 |
| `age` | `nlst_prsn.age` | 直接取值，特殊缺失码转未知 | 未核验 | 仅结构 | 描述 |
| `gender` | `nlst_prsn.gender` | 去空白，特殊缺失码转未知 | category | 仅结构 | 描述 |
| `race` | `nlst_prsn.race` | 去空白，特殊缺失码转未知 | category | 仅结构 | 描述 |
| `cigsmok` | `nlst_prsn.cigsmok` | 去空白，特殊缺失码转未知 | category | 仅结构 | 描述 |
| `index_scr_days` | `nlst_prsn.scr_days1` | 直接取值，保留原始正负偏移 | days_since_randomization | 已核验 | **特征** |
| `ct_screen_rounds` | `nlst_screen.study_yr` | 按 pid 统计轮次去重个数 | count | 仅结构 | 描述 |
| `screen_observed_t0` | `nlst_screen.study_yr` | 该轮是否有筛查记录 | boolean | 仅结构 | 描述 |
| `screen_observed_t1` | `nlst_screen.study_yr` | 该轮是否有筛查记录（索引轮） | boolean | 仅结构 | 描述 |
| `screen_observed_t2` | `nlst_screen.study_yr` | 该轮是否有筛查记录 | boolean | 仅结构 | 描述 |
| `ab_records_t0` | `nlst_ctab` 行数 | 该轮异常记录行数；轮次未出现为 NULL | count | 仅结构 | 描述 |
| `ab_records_t1` | `nlst_ctab` 行数 | 该轮异常记录行数；轮次未出现为 NULL | count | 仅结构 | 描述 |
| `ab_records_t2` | `nlst_ctab` 行数 | 该轮异常记录行数；轮次未出现为 NULL | count | 仅结构 | 描述 |
| `ab_number_t1_max` | `nlst_ctab.sct_ab_num` | T1 最大编号 | index | 已核验 | 描述 |
| `ab_long_dia_t1_max` | `nlst_ctab.sct_long_dia` | T1 最大长径 | 未核验 | 仅结构 | 描述 |
| `ab_perp_dia_t1_max` | `nlst_ctab.sct_perp_dia` | T1 最大垂直径 | 未核验 | 仅结构 | 描述 |
| `ctabc_records_t1` | `nlst_ctabc` 行数 | T1 比较阅片记录行数 | count | 仅结构 | 描述 |
| `ctabc_unmatched_t1` | `nlst_ctabc` 行数 | 无法通过 pid、study_yr、sct_ab_num 连到同轮异常的记录行数 | count | 仅结构 | 描述 |

仓库内已核验的字典标签只有 `scr_days0/1/2`、`sct_ab_num`、`candx_days`、`canc_free_days`（见 [机器可读汇总](NLST_AUDIT_SUMMARY.json) 的 `critical_dictionary_labels`）。其中后两项属于结局且索引时点不可用，因此**只有 `index_scr_days` 进入可建模白名单** `MODELING_APPROVED_COLUMNS`。放宽白名单必须先完成字段语义审核并更新风险任务卡，不能靠改代码完成。

### 缺失与"未见异常"的区分

- `.N`、`.E`、`.W`、`.` 等有语义的特殊代码按来源含义记为未知，**不填 0**。
- 某轮没有筛查记录时，该轮异常记录数保持 NULL，不能因为表里没有行就当作未见异常。
- 轮次已出现但没有异常记录行是否等于"未见异常"**尚未复核**，因此 `ab_records_* = 0` 的临床含义按未定处理，写入了 `limitations`。

### 排除字段

诊断、分期、结局衍生字段与索引时点不可用字段不进入输出表，也不得成为特征；比较阅片描述与患者表筛查结果字段同样暂不复用。完整清单及理由见 `field_mapping.json` 的 `excluded_fields`。`excluded_conflicts()` 保证字段映射与排除清单不冲突，`test_only_reviewed_fields_are_approved_for_modeling` 守护该约束。

## 明确不做的事

1. **不生成标签。** 带 `--emit-labels` 运行只会得到拒绝：

   ```text
   refused: this adapter does not produce a label column. The NLST outcome task is
   BLOCKED_PENDING_FOLLOWUP_DEFINITION: the negative definition, censoring and report
   availability are unresolved (docs/RISK_TASK_NLST.md). Writing a label here would
   invent a reviewed outcome definition and could turn unobserved participants into negatives.
   ```

   缺少随访的受检者必须标未知或删失；把没有诊断记录当作阴性会直接制造错误的负样本。
2. **不把不同队列拼成同一受检者。** 输出的 `subject_id` 带队列前缀，跨来源同名编号不会因为按行拼接而合并；同一队列内 `nlst_prsn` 也不等于 CT 筛查队列（公开子集缺 `rndgroup`）。
3. **不下载 CT 影像**，也不声称患者表覆盖等于影像可下载覆盖。
4. **不把横断面分类改名为未来风险预测**。任务定义决定见 [公开数据候选对照](DATA_CANDIDATES.md#任务定义决定)。
5. 不直接替换 `workflow_models.py`，也不修改 `api/routes/workflow.py`；接入由负责人在契约评审后完成。

## 已知限制

1. 缺 `fup_days` 与死亡时间：阴性、删失与竞争事件定义未定。
2. `sct_ab_num` 每位受检者每个研究年从 1 重新编号，只能同轮关联，不是跨年病灶身份。
3. 公开子集没有报告可获得时间；`scr_days` 是相对随机化天数，不能编造公历日期或假设当天可用。
4. 患者表人群大于 CT 筛查人群，且缺 `rndgroup`。
5. 轮次未出现时该轮计数为 NULL；已出现但无记录行是否等于未见异常尚未复核。
6. 字段语义未复核的列只作描述性输出。
7. 患者级表覆盖不等于影像可下载覆盖。

## 验证

自动化测试覆盖：输出列与字段映射完全一致且不含 `label`；`subject_id` 队列命名空间与排序；轮次缺失时为未知而非 0；特殊缺失码不填 0；比较阅片无法关联行被计数；质量摘要不含受检者标识与标签；只有已复核字段进入建模白名单；标签生成被拒绝；未复核快照哈希被拒绝；非预期 `dataset_version` 被拒绝；输出目录拒绝覆盖。测试文件：`backend/tests/test_nlst_cohort.py`（本次 12 项全部通过）。

2026-09-18 验证：固定快照实际下载并通过哈希校验（`matches_reference_snapshot=true`）；两次独立运行输出一致；汇总与 [NLST 审计](NLST_AUDIT.md) 逐项对齐（见上一节）。完整后端测试 182 项通过，其中本分支新增 41 项；`ruff check app tests` 通过。

提交到版本库的 `docs/NLST_COHORT_QUALITY.json` 是 CLI 的原样输出。来源哈希与汇总计数应与本文一致；`features_sha256` 取决于本地 pandas / pyarrow 版本，不同环境可能不同，因此不把它当作跨环境指纹。
