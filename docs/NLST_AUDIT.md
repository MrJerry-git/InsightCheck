# NLST 公开临床子集审计

2026-09-16 实际下载审计。来源为 IDC v24，临床表内部版本为 `2011.02.03/05.12.21`，字段字典为 idc-index-data 24.2.2。IDC 发布版本较新不意味着受试者数据采集于 2026 年。

## 结论

已经取得公开观察性临床数据，能够开展表结构、同轮异常关联和多轮筛查覆盖审计。**当前暂不冻结未来肺癌风险任务，也不生成真实风险模型指标。** 这不是认定 NLST 完全不可用，而是当前目标的阴性定义、删失和时间可获得性尚未充分核实。

| 表 | 行数 | 独立受检者 | 用途 |
| --- | ---: | ---: | --- |
| nlst_prsn | 53,452 | 53,452 | 人口学、各轮筛查结果与部分结局 |
| nlst_screen | 75,138 | 26,453 | CT 筛查参数 |
| nlst_ctab | 177,487 | 24,517 | 当轮异常及测量 |
| nlst_ctabc | 31,046 | 11,178 | 当轮比较阅片描述 |
| nlst_canc | 2,150 | 2,058 | 肺癌诊断与病理分期 |

5 张临床表合计 2,425,517 字节，不含影像。每表按预期主键检查：重复键行数、缺失键行数和患者表外关联行数均为 0。比较阅片表仍有 **18 行无法通过 pid、study_yr、sct_ab_num 连接到同轮异常表**，不能静默当作已匹配或新发病灶。

CT 筛查表中有 1 / 2 / 3 轮记录的人数分别为 1,351 / 1,519 / 23,583。患者表包含更大人群；公开子集没有 rndgroup，因此不能仅凭患者表筛查结果推定其属于 CT 组。原始表覆盖也不等于影像可下载患者覆盖。

## 阻止直接训练的字段问题

1. `candx_days` 是距随机化首次肺癌诊断的天数，2,058 人有数值。缺少诊断日不等于完成观察且未发生癌症。
2. `canc_free_days` 虽有 53,452 个数值，但官方字典提醒它不应用作肺癌发生率或 Cox 等分析的随访时间，推荐非病例使用 `fup_days`。公开患者表缺少该字段，也缺少死亡时间。不能悄悄替代随访截止日。若研究保守的固定窗口可观察子集，仍需单独评估选择偏倚并确认阴性与竞争事件定义。
3. `sct_ab_num` 在每位患者每个研究年重新从 1 编号，只能用于同轮两表关联。它不是跨年病灶身份真值；不能把编号相同作为同一病灶。
4. `scr_days0/1/2` 是相对随机化的天数，不是报告可获得时间。T0 数值范围包含 -4 天；保留原始偏移，不能编造公历日期或粗暴改成 0。
5. `.N`、`.E`、`.W` 等是有语义的特殊代码。汇总审计将其计入非数值缺失类别，建模前必须按字段含义区分“不适用”“诊断后检查”“错误检查”等，不能统一填 0。
6. 分期、最终病理、诊断日和患者表肿瘤部位/大小等结局衍生字段不得作为索引时点的常规特征。列名相似不代表与当轮 CT 观测来源相同。

完整字段、非数值缺失计数、时间范围、文件 SHA256、关联检查见 [机器可读汇总](NLST_AUDIT_SUMMARY.json)。该汇总不含个人标识、个体记录或患者划分。

## 来源、许可和复现

- [NCI 官方数据目录](https://cdas.cancer.gov/datasets/nlst/)区分公开子集与需审批、协议的完整数据。
- [IDC 官方教程](https://github.com/ImagingDataCommons/IDC-Tutorials/blob/master/notebooks/collections_demos/nlst_clinical_data.ipynb)说明公开临床表访问方式；下载脚本依据官方客户端公开存储桶路径，仅下载固定版本 NLST 临床表。
- [TCIA 集合页](https://www.cancerimagingarchive.net/collection/nlst/)将临床数据列为 CC BY 4.0；使用和发表时保留数据引用及许可要求。本仓库不再分发患者级文件。
- 数据引用：National Lung Screening Trial Research Team (2013), Data from the National Lung Screening Trial (NLST), The Cancer Imaging Archive, https://doi.org/10.7937/TCIA.HMQ8-J677。

在 backend 目录执行：

```powershell
.venv/Scripts/python.exe -m pip install -e '.[dev,research]'
.venv/Scripts/python.exe -m app.research.nlst ../data/raw/nlst --download --output ../data/processed/nlst/audit.json
```

脚本固定 URL 和本次实测 SHA256，下载变化或缓存哈希不符时失败，保留文件待复核。时间戳会随重新审计变化；数据版本、哈希和统计应一致。`data/` 在 Git 忽略范围内。

下一步先完成 [NLST 风险任务卡](RISK_TASK_NLST.md) 的未决条件。若无法形成足够可靠的标签，则申请完整数据或更换已核验的纵向来源；不把横断面分类改名为未来风险。
