# Synthea 合成数据导入

首版范围：官方 CSV ZIP → 小型标准导入包 → 校验 → 幂等入库 → 页面历史查询。只支持 synthetic 来源，暂不接受合作方真实资料。

## 环境

Windows Python 3.12 环境已在本机重新建立。其他机器先安装 Python 3.12，在 backend 下创建 .venv；不要复制原 iCan 的虚拟环境。

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-win-py312.lock.txt
.venv/Scripts/python.exe -m pip install --no-deps -e .
.venv/Scripts/python.exe -m alembic upgrade head
```

锁文件记录本次 Windows/Python 3.12 的运行和测试依赖版本，不是带哈希的跨平台锁。构建工具仍由 pyproject.toml 的 build-system 提供。其他平台按 pyproject.toml 安装并独立验证。前端在 frontend 下运行 `npm ci`；如全局 npm 缓存不可写，使用 `npm ci --cache ../.runtime/npm-cache`。

## 下载与转换

从项目根目录执行：

```powershell
New-Item -ItemType Directory -Force data/raw/synthea
Invoke-WebRequest -Uri 'https://synthetichealth.github.io/synthea-sample-data/downloads/latest/synthea_sample_data_csv_latest.zip' -OutFile 'data/raw/synthea/synthea_sample_data_csv.zip'
```

进入 backend 后生成审计报告和页面可用的 bundle.json：

```powershell
.venv/Scripts/python.exe -m app.importing ../data/raw/synthea/synthea_sample_data_csv.zip --audit-output ../data/processed/synthea/audit.json --bundle-output ../data/processed/synthea/bundle.json
```

以上命令不写入数据库。校验失败退出码为 2，报告含表名、CSV 行号和字段。ZIP 无需解压，不执行其中任何内容；适配器仅读取患者、就诊和观测三个表。

命令行入库：

```powershell
.venv/Scripts/python.exe -m app.importing ../data/raw/synthea/synthea_sample_data_csv.zip --audit-output ../data/processed/synthea/import-result.json --import-data
```

页面入库：启动前后端，打开 `/health-records`，选择刚生成的 bundle.json。校验通过后点“确认导入”；再加载患者列表并选择患者查看历史。也可只查看已经由命令行导入的记录。

## 标准导入包

JSON 包含 source_dataset=synthea、source_kind=synthetic、source_version=原 ZIP SHA256、adapter_version=synthea-wellness-v1，以及以下三个 CSV 字符串。额外列与额外 JSON 字段会被拒绝，避免误传身份信息。

| CSV | 表头 |
| --- | --- |
| patients_csv | source_id,birth_date,gender |
| encounters_csv | source_id,patient_source_id,event_time,encounter_type |
| observations_csv | source_id,patient_source_id,encounter_source_id,event_time,code,original_name,original_value,original_unit |

时间必须带时区，持久化来源快照统一为 UTC；encounter_type 只能为 wellness。跨患者关联、重复 source_id、无效日期、无时区、非有限数、未知代码和不匹配单位均阻止整包写入。允许有效记录缺少观测，但不把缺少观测解释为正常。

API：POST `/api/v1/imports/validate` 只做校验；POST `/api/v1/imports` 校验并写入；GET `/api/v1/imports/patients` 读取导入患者；GET `/api/v1/imports/patients/{id}/timeline` 读取来源和历史。患者列表上限 1000，时间线默认最近 100 次、最多 200 次，返回 truncated 标记。

## 映射与边界

只接收 wellness 就诊下五类数值：8302-2 身高 cm、29463-7 体重 kg、39156-5 BMI kg/m2、8480-6 收缩压 mm[Hg]、8462-4 舒张压 mm[Hg]。其余观测按非目标就诊、非数值、未映射分别计数。不推断正常范围，不生成疾病标签或风险分数，不把就诊行为当作医学适宜性。

当前单位只允许与映射完全一致，不作未经核验的单位换算。原始名称、数值、单位与观测时间保留；导入指标放在 SYN_LOINC 命名空间，避免覆盖真实临床字典。

源文件不含 available_at，保存为未知，不把观测日期当成报告实际可用日期。时间线用于查看，不可直接宣称满足模型防泄漏要求。模型接入前还需专门的按时点特征适配器。

## 幂等、事务与来源

来源实体 ID 由数据集、ZIP 哈希、实体类别和源 ID 确定；观测源 ID 使用原文件行号，与 ZIP 哈希绑定。同一包重放复用实体，返回 created/reused；同版本记录内容变化、目标记录被删除或导入器负责的字段被修改则返回 409，不静默覆盖。写入过程中异常会回滚整包。

ImportBatch 保存来源版本和导入计数；ImportedRecord 保存经过允许字段筛选的来源快照与哈希。不同 ZIP 版本刻意隔离，不能当作新的一批独立患者直接混入同一研究实验；跨版本身份对齐不在 v1 范围内。

这不是并发高吞吐 ETL 服务。首版限制 1000 人、20000 次就诊、50000 条观测；适用于小型合成开发集。正式多用户真实资料导入、鉴权、批次撤销、任意 CSV 和临床数据审计尚未实现。
