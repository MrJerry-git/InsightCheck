# InsightCheck 循影定检

## 比赛版入口：心血管体检规划

[下载参赛版前端演示与测试资料包](docs/competition-test-kit/README.md)：仿真报告 PDF、图片、文字、边界场景与验收清单。

新增 PREVENT 实际风险计算、历史指标轨迹、下一年度检查建议、报告保存回看与导出。
双击 `start-competition.cmd`，或打开 `http://127.0.0.1:3030/competition`。
双击 `stop-competition.cmd` 停止比赛脚本创建的服务。
基础计算无需 R、GPU 或模型服务密钥。新增“体检资料智能导入”使用本地 Qwen3-VL 4B，
首次双击 `start-smart-import.cmd` 安装模型；需要额外内存/显存，见
[智能导入说明](docs/SMART_IMPORT.md)。完整操作、数据核验及适用边界见
[比赛版说明](docs/COMPETITION_EDITION.md)和[第三方许可](THIRD_PARTY_NOTICES.md)。
这是范围收敛后的参赛闭环，不代表原 2.0 全范围已完成或临床有效性已验证。

以下为原平台建设背景与基础环境说明。

本项目以《循影定检——基于 LightGBM 与 DeepFM 的个性化体检方案推荐》申报书为建设目标。参与 iCan 是推动项目改进与实现的阶段性实践；InsightCheck 统一管理后续的源码、技术文档和研究进展。

当前基础来自 iCan 原型，包含数据标准化、纵向特征、病灶匹配、DeepFM 和规则引擎实现。现已接通档案、历史分析、合成 LightGBM + DeepFM 推理、规则检查和方案保存回看闭环；真实数据模型实验尚未完成。DeepFM 匹配分数必须经过规则引擎，仍不是疾病概率或最终体检方案。

- [1.0 工程预览使用与验收](docs/V1_WORKFLOW.md)
- [2.0 多系统平台设计、分工与验收（当前任务）](docs/TEAM_TASKS_V2.md)
- [前期 1.0 分工记录](docs/TEAM_TASKS_V1.md)
- [实施设计与共同开发基线](docs/IMPLEMENTATION_DESIGN.md)
- [公开数据选型与替代计划](docs/DATASET_PLAN.md)
- [仓库内容审查](docs/REPOSITORY_REVIEW.md)
- [风险任务卡模板](docs/RISK_TASK_TEMPLATE.md)
- [Synthea 导入与页面操作](docs/SYNTHETIC_IMPORT.md)
- [Synthea 小样本实测](docs/SYNTHEA_AUDIT.md)
- [NLST 公开临床子集审计](docs/NLST_AUDIT.md)
- [NLST 风险任务候选与未决条件](docs/RISK_TASK_NLST.md)
- [离线风险基线程序](docs/RISK_EXPERIMENTS.md)
- [开发路线与验收标准](docs/ROADMAP.md)
- [Git 协作与环境重建](docs/CONTRIBUTING.md)

本仓库不包含本地数据库、虚拟环境、真实体检资料和申报书中的个人信息。演示数据通过下文的 seed 命令生成；独立 HTML Demo 仅用于交互参考，其演示结果不代表模型实验成果。

2026-09-20 规划更新：2.0 不再限定单一疾病，建设覆盖常见基础体检类别的多系统平台。陈子正负责全部前端，王天一负责业务后端与集成，王宏锦负责解析、分析、规则内容与模型服务。资料处理、规则推荐、三档预算、审核和报告必须真实可用；依赖真实数据的训练与效果验证逐任务列为待办。本次更新是设计与任务书发布，不代表 2.0 软件已实现，具体范围与完成标准以当前任务书为准。

截至 2026-09-16，申报书所述合作方数据尚未取得。过渡期优先使用 Synthea 做工程联调，审计 NLST 公开临床子集的纵向实验可行性；二者不能替代合作方人群中的最终验证。下载与字段核验状态见数据计划。

当前已新增 Synthea 小样本适配、CSV 校验、来源记录、事务性幂等导入和 `/health-records` 历史查询页面。本机已导入 108 名合成患者；该批数据仅用于工程联调，不代表医学有效性证据。

2026-09-17：NLST 公开临床表审计及 Logistic、随机森林、LightGBM 离线实验程序已完成。程序通过合成夹具测试；真实风险任务尚未冻结，未训练 NLST 模型，也未接入在线风险服务。

## 产品边界

系统基于历史体检数据提供健康趋势分析与体检项目辅助推荐。LightGBM 将负责健康风险预测，DeepFM 将负责 Patient × ExamItem 匹配，规则引擎将负责安全约束，LLM 只负责结构化结果的总结、解释和问答。

LLM 不拥有最终项目推荐权，后续实现也不得把原始体检报告直接交给 LLM 决定推荐项目。

> 本系统基于历史体检数据提供健康趋势分析与体检项目辅助推荐，不构成疾病诊断、医疗处方或治疗建议，最终体检方案应由具有资质的医务人员结合实际情况确认。

## 仓库结构

```text
.
├── frontend/        # Next.js、TypeScript、Tailwind CSS、shadcn/ui、ECharts
├── backend/         # FastAPI、SQLAlchemy、Pydantic、Alembic
├── .env.example     # 前后端环境变量模板
├── ARCHITECTURE.md  # 系统架构与扩展设计
├── CONTEXT.md       # 领域词汇与不变量
├── DATA_DICTIONARY.md # 数据字典与标准化规则
├── LESION_MATCHING.md # 病灶匹配与趋势契约
├── FEATURE_ENGINEERING.md # 指标纵向特征契约
└── RECOMMENDATION_MODEL.md # DeepFM、评估、制品与算法审计
```

### Windows 双击启动

首次按下文安装前后端依赖后，双击仓库根目录的 `start-xunying.cmd`。脚本会自动执行 Alembic 迁移、在后台启动 FastAPI 与 Next.js，等待服务就绪，然后打开：

- 前端仪表盘：`http://127.0.0.1:3000/dashboard`
- 后端 API 文档：`http://127.0.0.1:8000/docs`

运行日志和 PID 保存在 `.runtime/`（已加入 `.gitignore`）。脚本不会自动安装依赖；依赖缺失时会给出明确提示。

## 本地启动

### 1. 开发环境要求

- Node.js：`^20.19.0`、`^22.12.0` 或 `>=24.0.0`，推荐 Node.js 24；
- npm：`>=10.0.0`，本项目锁文件由 npm 11.16.0 生成；
- Python：`>=3.11`，推荐 Python 3.12；
- 包管理：前端使用 npm 与 `package-lock.json`，后端使用 `pyproject.toml` 与 pip。

### 2. 环境变量

开发环境使用代码内默认值即可启动，不强制创建 `.env`。需要覆盖后端配置时，在仓库根目录复制 `.env.example` 为 `.env`；需要覆盖前端 API 地址时，在 `frontend/.env.local` 中设置 `NEXT_PUBLIC_API_BASE_URL`。Next.js 不会自动读取仓库根目录的 `.env`。

原有独立排名 API 只有在 `RECOMMENDATION_ARTIFACT_PATH` 指向已验证 DeepFM 制品目录时才提供分数；未加载模型时返回 HTTP 503，不使用随机或写死结果。新工作台 `/workflow` 使用独立的合成演示模型，仅对合成记录运行，并明确标注合成任务概率；不能替代正式制品。

### 3. 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,research]"
python -m alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

`python -m app.seed` 会幂等创建基础体检 Demo，以及一个 2023—2026、尺寸为 5.0 / 5.3 / 5.8 / 6.2 mm 的纵向病灶 Demo。所有体检批次均明确标记 `is_demo=true`，影像文字和项目说明标记 `DEMO DATA`；Seed 不创建风险预测、推荐、医疗规则或 AI 报告。

存活检查：`GET http://localhost:8000/health`

版本化健康检查：`GET http://localhost:8000/api/v1/health`

需要连接 PostgreSQL 的环境另行安装 `python -m pip install -e ".[postgres]"`，并将 `DATABASE_URL` 改为对应的 SQLAlchemy PostgreSQL URL。

### 4. 前端

```powershell
cd frontend
npm install
npm run dev
```

前端地址：`http://localhost:3000`

## 测试

```powershell
cd backend
python -m ruff check app tests alembic
python -m pytest

cd ..\frontend
npm test
npm run lint
npm run typecheck
npm run build
```

## 当前阶段状态

已完成：工程骨架、15 个领域实体、数据标准化、病灶匹配与变化分析、历年指标特征工程、真实 PyTorch DeepFM 推荐模型，以及版本化、可追溯、确定性冲突裁决的医疗规则引擎。

本轮新增：受检者创建、手工记录、历史及病灶查看、合成模型推理、实际规则执行、方案事务保存、历史回看、JSON 证据导出、本地模板说明，以及项目和规则管理。详见 [使用说明](docs/V1_WORKFLOW.md)。

未完成：合作方数据导入、完整指标/单位/病灶术语治理、第五阶段 LightGBM 风险制品、真实推荐交互数据及时间外实验、经医学审核的实际规则、三档方案生成、LLM 供应商适配、鉴权和部署。现有模型与规则演示数据不得当作真实实验指标或临床指南。
