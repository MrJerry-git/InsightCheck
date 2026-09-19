# 公开数据候选对照与任务定义决定

负责人：王宏锦（分支 `feat/public-data-model`）。日期：2026-09-18。

本文只整理仓库内已经实际核验过的内容。**没有在仓库内实际下载或复核过的项目一律标为未核验**，不凭记忆或常识填写，也不用未核验的镜像绕过申请或授权条件。结论不能替代研究方案与专业审核。

## 结论

1. 三个候选都不需要个人申请即可访问：NLST 公开临床子集（已实测下载审计）、Synthea 合成样例（已实测下载并限定导入）、NHANES（官方公开调查数据，本仓库尚未实际下载）。
2. 本轮公开数据**只能支持当次（同轮）异常分类**，不能包装成未来事件预测。依据见下文"任务定义决定"。
3. 真正需要的"通用体检项目适宜性真值"仍然没有找到并核验；推荐质量不能靠这些来源解决。

## 候选一：NLST 公开临床子集（真实观察性数据，已核验）

| 项目 | 内容 |
| --- | --- |
| 数据主页 | [NCI CDAS NLST 目录](https://cdas.cancer.gov/datasets/nlst/)；公开子集访问方式见 [IDC 官方教程](https://github.com/ImagingDataCommons/IDC-Tutorials/blob/master/notebooks/collections_demos/nlst_clinical_data.ipynb) |
| 许可或使用条款 | [TCIA 集合页](https://www.cancerimagingarchive.net/collection/nlst/)将临床数据列为 CC BY 4.0；使用和发表须保留数据引用。数据引用：National Lung Screening Trial Research Team (2013), Data from the National Lung Screening Trial (NLST), The Cancer Imaging Archive, https://doi.org/10.7937/TCIA.HMQ8-J677 |
| 下载方式 | 固定版本 IDC v24 公开存储桶路径，由 `app.research.nlst` 按实测 SHA256 下载；下载变化或缓存哈希不符时失败并保留文件待复核 |
| 下载状态 | 5 张临床表合计 2,425,517 字节已实际下载并审计，另加 135,411 字节字段字典；未下载任何 CT 影像 |
| 字段 | `nlst_prsn` 41 列、`nlst_screen` 22 列、`nlst_ctab` 14 列、`nlst_ctabc` 12 列、`nlst_canc` 36 列；完整列表与非数值缺失计数见 [机器可读汇总](NLST_AUDIT_SUMMARY.json) |
| 标签 | 有 `candx_days`（2,058 人有值）与 `canc_free_days`（53,452 人有值）；官方字典明确 `canc_free_days` 不得用作肺癌发生率或 Cox 分析的随访时间，应改用 `fup_days`，而公开子集**缺 `fup_days` 与死亡时间** |
| 人数 | `nlst_prsn` 53,452 人；`nlst_screen` 26,453 人；`nlst_ctab` 24,517 人；`nlst_ctabc` 11,178 人；`nlst_canc` 2,058 人 |
| 时间信息 | `scr_days0/1/2` 是相对随机化的天数（T1 范围 116—755 天，T0 含 -4 天）；**报告何时可获得未知**，不能假定检查当天可用，也不能编造公历日期 |
| 适配局限 | 缺 `rndgroup`，不能仅凭患者表推定 CT 组；`sct_ab_num` 每位受检者每个研究年从 1 重新编号，不是跨年病灶身份；18 行比较阅片记录无法连到同轮异常；公开子集不足以代表中国体检人群 |

已写出可复现的读取与转换入口，见 [NLST 受检者级适配入口](NLST_COHORT.md)。

## 候选二：Synthea 合成样例（合成数据，已核验）

| 项目 | 内容 |
| --- | --- |
| 数据主页 | [Synthea 官方下载页](https://synthetichealth.github.io/downloads.html) |
| 许可或使用条款 | 仓库记录为"官方允许这些合成数据广泛使用，仍应保留引用来源"；**具体许可名称与条款文本未核验** |
| 下载方式 | [CSV ZIP](https://synthetichealth.github.io/synthea-sample-data/downloads/latest/synthea_sample_data_csv_latest.zip)。`latest` 会变化，下载时必须记录日期与 SHA256，不能仅写 latest |
| 下载状态 | 已实测：文件 5,960,866 字节，SHA256 `d61417b5…0907c35` |
| 字段 | 本次只映射 wellness 就诊的 5 个观测代码：身高（cm）、体重（kg）、BMI（kg/m2）、收缩压、舒张压（mm[Hg]）。身份字段未进入标准导入包 |
| 标签 | **没有真实标签**。合成数据不携带真实疾病结局，不能用于风险准确率或推荐质量结论 |
| 人数 | 实测 108 名患者、5,571 条就诊、68,648 条观测；限定导入 108 / 1,262 / 4,396 |
| 时间信息 | 有 `event_time`，但来源不含报告可获得时间，导入记录的 `available_at` 保持 unknown |
| 适配局限 | 不保证存在结节轨迹；不能证明真实风险准确率或真实推荐质量；无临床参考区间 |

用途：工程联调、时间线、导入接口与方案流程验证。详见 [Synthea 实测记录](SYNTHEA_AUDIT.md)。

## 候选三：NHANES（真实公开调查数据，本仓库尚未核验）

| 项目 | 内容 |
| --- | --- |
| 数据主页 | [NHANES 2017—2018 官方数据目录](https://wwwn.cdc.gov/nchs/nhanes/continuousnhanes/default.aspx?BeginYear=2017)；横断面性质说明见 [CDC 可视化页](https://www.cdc.gov/nchs/nhanes/visualization/) |
| 许可或使用条款 | **未核验**（仓库内只记录了官方公开调查数据这一属性，未逐条阅读使用条款） |
| 下载方式 | **未核验**（仓库内没有实际下载记录，`data/` 下无 NHANES 文件） |
| 字段 | **未核验**（未列出检查、问卷与实验室数据的具体字段清单） |
| 标签 | 无随访，只能定义**当次异常分类**；且必须排除直接构成标签的同次指标，不能包装成未来风险预测 |
| 人数 | **未核验**（未在仓库内统计任何周期的人数） |
| 时间信息 | 横断面；**不同周期不是同一人随访**，调查权重、分层与抽样设计须按分析目标处理 |
| 适配局限 | 不能验证同一人历年指标或病灶变化；跨周期直接合并会把不同个体当成同一受检者 |

入选理由与理由同样的坦诚：它是唯一的标准化横断面表格基线候选（见 [数据选型与过渡计划](DATASET_PLAN.md)），但在实际下载并列出字段清单之前，所有具体数量都保持未知。

## 明确不列入候选的来源

| 来源 | 原因 |
| --- | --- |
| NLST 完整临床数据（CDAS） | 需要项目审批与数据协议，尚未获批，不能称为已拥有 |
| MIMIC-IV | 需要认证、培训与数据使用协议，且不等价于健康体检人群与项目适宜性，暂不优先 |

绕过访问要求的镜像不会被使用。参见 [MIMIC 官方访问说明](https://mimic.mit.edu/docs/faq/how-to-get-access.html)。

## 任务定义决定

**本轮结论：只能做当次（同轮）异常分类；未来事件预测保持 BLOCKED。**

| 任务类型 | 现有公开数据能否支持 | 依据 |
| --- | --- | --- |
| 当次（同轮）异常分类 | 结构上可支持，但须先通过字段语义审核 | `nlst_ctab` 与同轮 `nlst_ctabc` 可按 `pid`、`study_yr`、`sct_ab_num` 关联；`scr_days` 提供索引时点 |
| 未来事件预测（如"T1 后 365 天首次肺癌诊断"） | **不能** | 缺 `fup_days` 与死亡时间，阴性/删失/竞争事件定义未定；报告可获得时间未知；`canc_free_days` 被官方字典禁止用作随访时间 |

具体要求：

1. 横断面数据只能支持相应分类验证，**不能改名成纵向预测**。任务卡必须写明 `task_kind`，二选一，不允许含糊。
2. 缺少诊断记录不等于观察完整且未发生。没有足够随访的受检者标为未知或删失，不得填 0。
3. 不能为了解除 BLOCKED 而填写未经审核的结局定义或审核记录。未决条件见 [NLST 风险任务卡](RISK_TASK_NLST.md)。
4. 适配入口拒绝 `--emit-labels`，理由随拒绝信息一起给出（见 `app/research/nlst_cohort.py`）。

## 跨队列合并规则

1. **不同队列不得按行拼成同一受检者。** NLST 适配入口输出的 `subject_id` 带队列前缀（`nlst-idc-v24:`），两个来源的同名编号不会因为拼接而合并成一个人。
2. 同一队列内部：`nlst_prsn` 的 53,452 人不等于 CT 筛查队列；公开子集缺 `rndgroup`，不能凭患者表筛查结果推定分组。
3. 合成数据与真实数据不得混入同一训练集；合成制品必须保留合成标签，见 [风险模型制品契约](RISK_MODEL_ARTIFACT.md)。
4. 任何跨来源合并都需要可核验的患者标识与时间对齐依据，目前没有这样的依据。

## 本轮交付物

| 交付 | 位置 |
| --- | --- |
| 数据候选对照（本文） | `docs/DATA_CANDIDATES.md` |
| 可复现适配入口、字段映射与质量摘要 | [`app/research/nlst_cohort.py`](../backend/app/research/nlst_cohort.py)、[说明](NLST_COHORT.md) |
| 制品加载与预测适配器、模型加载契约 | [`app/ml/risk/`](../backend/app/ml/risk/)、[说明](RISK_MODEL_ARTIFACT.md) |
| 测试 | `backend/tests/test_nlst_cohort.py`、`backend/tests/risk/test_artifact.py` |
