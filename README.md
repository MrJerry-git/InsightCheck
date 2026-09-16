# InsightCheck 循影定检

本项目以《循影定检——基于 LightGBM 与 DeepFM 的个性化体检方案推荐》申报书为建设目标。参与 iCan 是推动项目改进与实现的阶段性实践；InsightCheck 统一管理后续的源码、技术文档和研究进展。

当前基础来自 iCan 原型，包含数据标准化、纵向特征、病灶匹配、DeepFM 和规则引擎实现。LightGBM 风险模型、真实数据实验及完整方案生成闭环尚未完成。DeepFM 匹配分数必须经过规则引擎，仍不是疾病概率或最终体检方案。

- [实施设计与共同开发基线](docs/IMPLEMENTATION_DESIGN.md)
- [公开数据选型与替代计划](docs/DATASET_PLAN.md)
- [仓库内容审查](docs/REPOSITORY_REVIEW.md)
- [风险任务卡模板](docs/RISK_TASK_TEMPLATE.md)
- [开发路线与验收标准](docs/ROADMAP.md)
- [Git 协作与环境重建](docs/CONTRIBUTING.md)

本仓库不包含本地数据库、虚拟环境、真实体检资料和申报书中的个人信息。演示数据通过下文的 seed 命令生成；独立 HTML Demo 仅用于交互参考，其演示结果不代表模型实验成果。

截至 2026-09-16，申报书所述合作方数据尚未取得。过渡期优先使用 Synthea 做工程联调，审计 NLST 公开临床子集的纵向实验可行性；二者不能替代合作方人群中的最终验证。下载与字段核验状态见数据计划。

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

排名 API 只有在 `RECOMMENDATION_ARTIFACT_PATH` 指向已验证 DeepFM 制品目录时才提供分数；未加载模型时返回 HTTP 503，不使用随机或写死结果。

### 3. 后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
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

未完成：真实数据导入、完整指标/单位/病灶术语治理、第五阶段 LightGBM 风险制品、真实推荐交互数据及时间外实验、经医学审核的实际规则、三档方案生成、LLM 供应商适配、鉴权和部署。现有模型与规则演示数据不得当作真实实验指标或临床指南。
