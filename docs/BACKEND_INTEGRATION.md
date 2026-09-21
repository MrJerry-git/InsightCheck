# 2.0 后端集成与前端联调说明（T12）

负责人：王天一。日期：2026-09-21。范围：T01—T12 后端交付、接口清单、可运行链路、
前端接入字段与已知未完成项。**本文不代表 2.0 全部验收完成**：前端 C01—C12 与
H 系列服务仍在各自分支/PR 中。

## 1. 交付状态一览

| 任务 | 内容 | 状态 | 交付位置 |
| --- | --- | --- | --- |
| T01 | 登录、会话、角色、账户初始化、档案访问控制 | 已实现（分支） | `feat/auth-access` PR #30 |
| T02 | 多系统档案与字典持久化、历史修订 | 已实现（分支） | `feat/record-revisions` PR #31 |
| T03 | 文件管理与导入任务 API | 已实现（分支） | `feat/import-tasks` PR #32 |
| T04 | 分析编排与结果保存 | 已实现（分支） | `feat/analysis-runs` PR #33 |
| T05 | 跨系统候选汇总与规则执行集成 | 已实现（分支） | `feat/analysis-runs` PR #33 |
| T06 | 三档方案与价格服务正式接入 | 已实现（分支） | `feat/plan-workflow` PR #34 |
| T07 | 编辑、复算、审核与方案快照 | 已实现（分支） | `feat/plan-workflow` PR #34 |
| T08 | 管理 API | 已实现（分支） | `feat/admin-api` PR #35 |
| T09 | 中文 PDF 与报告存储/下载 | 已实现（分支） | `feat/report-qa` PR #36 |
| T10 | 问答 API 及服务连接 | 已实现（分支，模型待 H08） | `feat/report-qa` PR #36 |
| T11 | 启停、迁移、部署、日志、健康检查、备份恢复 | 已实现（分支） | `feat/ops-deploy` PR #37 |
| T12 | 总体后端集成与前端联调 | 本文 + 端到端测试 | `feat/backend-integration` PR #38 |
| AI-T01—AI-T08 | 参赛版对话式体检档案管理后端 | 已实现（独立分支，279 测试通过） | `feat/conversational-import` PR #39 |

“已实现（分支）”指代码、迁移与自动化测试均在本分支上通过，**合并进 `main` 后才算对全体可见**。
合并顺序与依赖见每个 PR 描述（#30 → #31 → #32 → #33 → #34 → #35 → #36 → #37 → #38）。
`feat/conversational-import`（PR #39）从 `main` 独立建立，可与上述链条并行；
两者都合并时会出现两个 alembic head（都挂在 `e021a0b10001` 之后），
合并第二个 PR 时把其迁移的 `down_revision` 改到对方即可。

## 2. 接口面

干净检出上 `create_app().openapi()["paths"]` 共 **96 条路径**（`main` 基线为 51 条）。
按域划分（完整清单见 `docs/V2_API_CONTRACT.md` 与 `/docs`）：

| 域 | 前缀 | 说明 |
| --- | --- | --- |
| 账号 | `/api/v1/auth/*` | 登录、退出、本人改密、账号管理 |
| 档案与记录 | `/api/v1/patients`、`/health-checks`、`/lab-metrics`、`/imaging-exams`、`/exam-histories` 等 | 既有 CRUD + 归属过滤 + 修订号 |
| 修订历史 | `/api/v1/profiles/{id}/revisions`、`/records/{type}/{id}/revisions` | 变更前后快照、来源引用 |
| 导入任务 | `/api/v1/imports/tasks*` | 上传、预览、校对、确认、重试、取消 |
| 分析 | `/api/v1/analyses*` | 发现、候选、系统汇总、过期判定 |
| 方案 | `/api/v1/plans*` | 三档、预算、编辑复算、审核确认、修订快照 |
| 报告与问答 | `/api/v1/reports*`、`/api/v1/qa/*` | 中文 PDF、JSON 证据、依据问答 |
| 管理 | `/api/v1/admin/*` | 映射队列、价格、规则、模型状态、审计 |
| 运行 | `/health`、`/api/v1/health/detail` | 探活与部署明细 |
| 参赛版对话导入 | `/api/v1/prevention/conversation/*` | AI-T01—AI-T08：会话、草稿、确认、规划、新建档案（PR #39） |

旧接口（`/api/v1/workflow/*`、`/api/v1/prevention/*`、`/api/v1/imports`）保持可读，
其中 `/workflow/patients`、`/workflow/records`、`/workflow/plans` 已接入档案归属校验。

## 3. 端到端链路（已自动化验证）

`backend/tests/test_end_to_end.py` 用普通新建档案跑通完整链路，无任何外部模型依赖：

```
登录 → 新建档案 → 上传 CSV 导入任务 → 逐行校对 → 确认入库（写修订）
→ 分析（发现/候选/去重）→ 三档方案（真实价格、预算）
→ 编辑（填修改原因）→ 提交审核 → 确认 → 报告（修订回看 + 中文 PDF + JSON 证据）
→ 依据问答 → 修订历史 → 退出登录（令牌失效）
```

第二个用例把 `AUTH_REQUIRED=true`：未登录访问业务接口返回 401，`/health` 仍可探活，
登录后同一条链路仍可跑通，普通医生读 `/health/detail` 返回 403。

手工联调（前后端同时启动时）：

```bash
cd backend && uvicorn app.main:app --reload --port 8000     # 后端
cd frontend && npm run dev                                  # 前端（陈子正）
curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"doctor-a","password":"Doctor-Pass-2026!"}'
```

## 4. 前端接入要点

1. **统一鉴权**：登录后所有请求带 `Authorization: Bearer <token>`；401 表示需要重新登录，
   403 表示角色或档案归属不允许（两者语义不同，前端提示也要区分）。
2. **稳定标识**：档案 `patient_id`、任务 `task_id`、分析 `run_id`、方案 `plan_id`、
   修订 `revision_no`、记录修订 `entity_type + entity_id`，不要依赖列表顺序或名称。
3. **不隐藏按钮代替权限**：后端对写操作与越权访问都有校验；前端需展示 401/403 的真实返回。
4. **不本地计算**：费用、预算、规则结论、过期判定、可用能力一律以服务端返回为准；
   `score` 为空表示模型未接入，不要用 0 分或本地估算填充。
5. **过期与版本**：`analyses`、`plans`、`reports` 都返回版本与 `stale` 标记；
   资料变化后必须提示重新分析，旧版本用于只读回看。
6. **空态与未知**：`missing_information`、`notes`、`warnings`、`blocking_row_ids`、
   `unmapped_metric` 都要在界面上如实呈现，不能折叠成"正常"。

## 5. 运行与验证

```bash
cd backend
python -m pytest -q                    # 273 passed, 4 skipped（本分支）
python -m ruff check .                 # All checks passed
python -m alembic upgrade head         # 干净环境建表
python -m app.cli create-admin --username admin
python -m app.cli backup --output /var/backups/xunying
```

部署、HTTPS 与会话边界、备份恢复细节见 [部署文档](DEPLOYMENT.md)。

## 6. 尚未完成 / 需他人协作

| 事项 | 现状 | 需要 |
| --- | --- | --- |
| 前端 C01—C12 | 未接入 | 陈子正按本文与契约接入；`AUTH_REQUIRED` 切换与 C01 对齐 |
| 参赛版对话导入前端 | 未接入 | 陈子正接入对话组件、人体点亮、历史详情与"＋ 新建档案"（AI-T08 前端部分） |
| H 系列解析/分析服务 | 未合并 | 王宏锦合并后，把分析发现来源切到该服务（接口不变） |
| 疾病风险模型 / DeepFM | 未接入 | 数据到位后按 H09 训练与替换；当前不产生概率 |
| 语言模型问答 | 未接入 | 配置 `LLM_PROVIDER`/`LLM_BASE_URL` 后启用；未配置时结构化回答 |
| 真实报告版式质量 | 未评估 | H04 用真实版式对照，本仓库只用人工构造样例 |
| 公网部署 | 未提供服务器/域名 | 提供后按 `DEPLOYMENT.md` 上线并留存验收记录 |
