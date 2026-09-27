# 九华数据接入准备：导出契约与核验流程（H11）

负责人：王宏锦（WHJ-2007）。日期：2026-09-20。状态：**模板与契约阶段**——合作方数据尚未取得（见 README 2026-09-16 状态），本文与 `backend/app/jiuhua_prep/` 模块为数据到达前的准备交付物，不表示已接入任何真实数据。

## 一、交付格式要求（对合作方）

1. **格式**：CSV（UTF-8 编码，首行表头）或 Excel；每批次一个文件。
2. **批次溯源**：每批次提供批次号（映射模板 `batch_id`）；平台入库时写入 `ImportBatch` 的 `source_dataset="jiuhua"`、`source_kind="partner_observational"`、`adapter_version`（见 `app/jiuhua_prep/anonymization.py` 的 `batch_provenance()`）。
3. **字段**：按 `backend/app/jiuhua_prep/data/jiuhua_field_mapping_template.json` 的 `source_field` 交付；模板未登记的字段可一并交付，平台会进入待确认清单并逐条登记，不会猜测映射。
4. **隐私硬边界（必须）**：
   - 不得包含：姓名、身份证号、手机号、家庭住址、精确出生日期；
   - 受检者标识仅提供机构内编号（`person_id`），平台入库前经 `anonymize_identifier()` 生成确定性匿名码（uuid5 + 项目盐值），盐值由项目组保管、不进 Git 与数据文件；
   - 原始文件与导入库物理隔离，原始文件不落平台存储。
5. **标签与随访**：若存在疾病标签、随访结果字段，请一并交付；平台侧一律先标 `to_be_verified`（见质量摘要），在完成字段含义核验前不用于任何模型训练。

## 二、数据到达后的核验流程

1. **质量审计先行**：用 `summarize_quality()` 对样例文件（先脱敏小样本）输出逐字段计数、缺失率、取值样例；与合作方逐字段确认含义，更新映射模板 `verification_status`（unverified → verified）。
2. **映射冻结**：模板全部条目 verified 后冻结版本（`jiuhua-field-mapping-v1` → v2…），旧模板保留。
3. **适配器实现**：参照 `app/importing/synthea.py` 的"契约校验 + 原始快照 + 幂等导入"模式实现 `jiuhua.py` 适配器；进同一套标准数据契约（`docs/IMPLEMENTATION_DESIGN.md` 第五节），不虚构患者、不拼接批次。
4. **模型任务联动**：数据核验通过后，更新 H09 模型任务注册表（`partner-cohort-risk-models`）的状态与任务卡，先冻结任务卡再谈训练（见 `docs/RISK_TASK_TEMPLATE.md`）。

## 三、当前状态（诚实记录）

- [x] 字段映射模板初稿（14 条，全部 unverified）
- [x] 质量摘要工具（含标签/随访 to_be_verified 标记）
- [x] 匿名标识与批次溯源契约
- [x] 本导出契约文档
- [ ] 合作方数据字典（待提供）
- [ ] 样例数据核验（待数据到达）
- [ ] jiuhua.py 适配器（待映射冻结后实现）
- [ ] 标签/随访可用性确认（to_be_verified）
