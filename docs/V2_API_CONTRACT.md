# InsightCheck 2.0 接口契约（V2_API_CONTRACT）

负责人：王天一（T01—T12）。版本：v2.0-draft-3，日期：2026-09-21。

本文档登记 2.0 的全部接口与其真实状态。第 2 节是**当前 `main`** 已有能力，第 3 节是
T01—T12 已实现但尚未合并的分支能力，第 4 节是仍未实现的部分。状态定义见第 0 节。

## 0. 交付状态与核对方式

状态只有三种，含义严格区分：

| 标签 | 含义 |
| --- | --- |
| **已实现（main）** | 已合入 `main`，在干净检出上可直接调用 |
| **已在未合并分支实现** | 代码存在但**尚未合入 `main`**，不能作为 `main` 现有能力；分支与依赖单独列出 |
| **计划中** | 尚未实现，只登记契约形态，落地前不对外承诺 |

核对方式（2026-09-21，干净 `main` 检出）：`git checkout origin/main` 后执行

```bash
cd backend && PYTHONPATH=. python -c "from app.main import create_app; print(len(create_app().openapi()['paths']))"
```

结果：**51 条路径**（`main` 基线），清单见第 2 节。该清单里**没有** `/api/v1/auth/*`，配置中也没有
鉴权开关，`patients` 没有归属过滤——这些能力都在第 3 节列出的未合并分支里。
合并 T01—T12 后为 **96 条路径**。

## 1. 通用约定

| 项 | 约定 |
| --- | --- |
| 基础路径 | `/api/v1`（`settings.api_v1_prefix`） |
| 健康检查 | `GET /health`（根路径）与 `GET /api/v1/health`，均不需要登录，用于部署探活 |
| 认证 | 规划为 `Authorization: Bearer <token>`；**`main` 当前未启用**（见第 3 节） |
| 内容类型 | `application/json`；上传接口使用 `multipart/form-data` |
| 时间 | 日期 `YYYY-MM-DD`；时间戳 ISO 8601（UTC） |
| 金额 | 整数最小单位（分）+ 三字母币种；禁止浮点金额 |
| 分页 | 查询参数 `offset`（≥0）与 `limit`（1—500，默认 100） |
| 错误格式 | `{"detail": "<中文说明>"}`；请求校验失败为 422（FastAPI 默认结构） |
| 幂等 | 客户端生成 `request_id`/`Idempotency-Key`，重复提交返回首次结果 |
| 版本策略 | 路径带 `/api/v1`；破坏性变更新增字段或新路径，不修改既有字段语义 |

### 状态码

| 码 | 含义 |
| --- | --- |
| 200 / 201 / 204 | 成功 / 已创建 / 已删除 |
| 400 | 请求本身不合法（例如管理员停用自己） |
| 401 | 未登录、令牌无效、会话过期或已退出 |
| 403 | 已登录但角色或档案归属不允许 |
| 404 | 资源不存在（对无权访问也返回 404，避免探测他人档案） |
| 409 | 唯一性冲突、幂等冲突（同编号不同输入） |
| 422 | 参数/口令/业务规则校验失败 |
| 500 | 服务内部错误，响应不包含堆栈 |

## 2. 已实现（main，51 条路径，分类登记）

以下 51 条路径均在干净 `main` 上实测存在，方法按 OpenAPI 原样列出（`{entity_id}`/`{patient_id}`/
`{plan_id}` 为路径参数）。注意：这些接口**当前没有鉴权与归属过滤**，任何调用方可读写全部数据。

| # | 方法 | 路径 |
| --- | --- | --- |
| 1 | GET | `/health` |
| 2 | GET | `/api/v1/health` |
| 3 | GET, POST | `/api/v1/patients` |
| 4 | DELETE, GET, PATCH | `/api/v1/patients/{entity_id}` |
| 5 | GET, POST | `/api/v1/health-checks` |
| 6 | DELETE, GET, PATCH | `/api/v1/health-checks/{entity_id}` |
| 7 | GET, POST | `/api/v1/lab-metrics` |
| 8 | DELETE, GET, PATCH | `/api/v1/lab-metrics/{entity_id}` |
| 9 | GET, POST | `/api/v1/imaging-exams` |
| 10 | DELETE, GET, PATCH | `/api/v1/imaging-exams/{entity_id}` |
| 11 | GET, POST | `/api/v1/exam-histories` |
| 12 | DELETE, GET, PATCH | `/api/v1/exam-histories/{entity_id}` |
| 13 | GET, POST | `/api/v1/exam-items` |
| 14 | DELETE, GET, PATCH | `/api/v1/exam-items/{entity_id}` |
| 15 | GET, POST | `/api/v1/metric-dictionaries` |
| 16 | DELETE, GET, PATCH | `/api/v1/metric-dictionaries/{entity_id}` |
| 17 | GET, POST | `/api/v1/medical-rules` |
| 18 | DELETE, GET, PATCH | `/api/v1/medical-rules/{entity_id}` |
| 19 | GET, POST | `/api/v1/lesions` |
| 20 | DELETE, GET, PATCH | `/api/v1/lesions/{entity_id}` |
| 21 | GET, POST | `/api/v1/lesion-tracks` |
| 22 | DELETE, GET, PATCH | `/api/v1/lesion-tracks/{entity_id}` |
| 23 | GET, POST | `/api/v1/lesion-observations` |
| 24 | DELETE, GET, PATCH | `/api/v1/lesion-observations/{entity_id}` |
| 25 | POST | `/api/v1/lesion-terminology/normalize` |
| 26 | POST | `/api/v1/lesion-analysis/match` |
| 27 | POST | `/api/v1/lesion-analysis/trend` |
| 28 | GET | `/api/v1/lesion-analysis/demo` |
| 29 | GET, POST | `/api/v1/recommendations` |
| 30 | DELETE, GET, PATCH | `/api/v1/recommendations/{entity_id}` |
| 31 | GET, POST | `/api/v1/recommendation-items` |
| 32 | DELETE, GET, PATCH | `/api/v1/recommendation-items/{entity_id}` |
| 33 | GET, POST | `/api/v1/ai-reports` |
| 34 | DELETE, GET, PATCH | `/api/v1/ai-reports/{entity_id}` |
| 35 | GET, POST | `/api/v1/risk-predictions` |
| 36 | DELETE, GET, PATCH | `/api/v1/risk-predictions/{entity_id}` |
| 37 | POST | `/api/v1/metric-normalization/normalize` |
| 38 | POST | `/api/v1/rule-engine/evaluate` |
| 39 | POST | `/api/v1/recommendation-ranking/rank` |
| 40 | POST | `/api/v1/imports` |
| 41 | POST | `/api/v1/imports/validate` |
| 42 | GET | `/api/v1/imports/patients` |
| 43 | GET | `/api/v1/imports/patients/{patient_id}/timeline` |
| 44 | POST | `/api/v1/workflow/demo` |
| 45 | GET | `/api/v1/workflow/patients` |
| 46 | GET | `/api/v1/workflow/patients/{patient_id}` |
| 47 | POST | `/api/v1/workflow/records` |
| 48 | GET, POST | `/api/v1/workflow/plans` |
| 49 | GET | `/api/v1/workflow/plans/{plan_id}` |
| 50 | GET | `/api/v1/workflow/plans/{plan_id}/export` |
| 51 | POST | `/api/v1/workflow/plans/{plan_id}/explain` |

核对脚本（可复现，输出应为空）：用 OpenAPI 的 `paths` 与上表逐条比对，
见本文件第 0 节命令；补齐后 `实际路径集合 - 上表路径集合 = ∅`。

## 3. 已在未合并分支实现（不计入 main 现有能力）
## 3. 已在未合并分支实现（T01—T12 全部任务，合并后生效）

下表所有能力都已在对应分支上实现并有自动化测试，**尚未合入 `main`**。
合并顺序：#30 → #31 → #32 → #33 → #34 → #35 → #36 → #37 → #38（各 PR 的 base 为前一个分支）。

| 任务 | 依赖分支 | 交付内容 | 合并后新增能力 |
| --- | --- | --- | --- |
| T01 | `feat/auth-access` | 账号、会话、角色、档案归属 | `/auth/*` 8 条；业务接口鉴权与归属过滤 |
| T02 | `feat/record-revisions` | 值类型、来源、修订历史 | `/profiles/{id}/revisions`、`/records/{type}/{id}/revisions` |
| T03 | `feat/import-tasks` | 导入任务与校对确认 | `/imports/tasks*` 7 条 |
| T04 | `feat/analysis-runs` | 分析运行与结果保存 | `POST/GET /analyses`、`GET /analyses/{id}` |
| T05 | `feat/analysis-runs` | 跨系统候选汇总与规则集成 | `/analyses/{id}` 内的 findings/candidates/summary、`/analyses/finding-map` |
| T06 | `feat/plan-workflow` | 三档方案与价格接入 | `POST /plans`、`GET /plans/{id}`、`/plans/{id}/price-known` |
| T07 | `feat/plan-workflow` | 编辑复算、审核与快照 | `PATCH /plans/{id}`、`submit-review`、`confirm`、`revisions*` |
| T08 | `feat/admin-api` | 管理 API | `/admin/*` 10 条（映射、价格、规则、模型状态、审计） |
| T09 | `feat/report-qa` | 中文 PDF 与报告存储 | `/reports/{id}`、`/evidence`、`/pdf` |
| T10 | `feat/report-qa` | 问答 API | `POST /qa/ask`、`GET /qa/history` |
| T11 | `feat/ops-deploy` | 运行与运维 | `/health/detail`、结构化访问日志、`backup/restore` CLI |
| T12 | `feat/backend-integration` | 集成与联调 | 端到端测试与本文档更新 |
| AI-T01—AI-T08 | `feat/conversational-import` | 参赛版对话式档案管理后端 | `/api/v1/prevention/conversation/*`（独立于 T 系列，PR #39） |

合并后 `create_app().openapi()["paths"]` 为 **96 条路径**（当前 `main` 基线 51 条），
核对命令与第 0 节一致。

## 4. 计划中（仍未实现）

| 资源 | 计划路径 | 负责人 | 备注 |
| --- | --- | --- | --- |
| 疾病风险模型与 DeepFM 排序 | 复用 `/risk-predictions`、`/recommendation-ranking/rank` | 王宏锦（王天一接入） | 数据到位后训练与替换；当前分析结果中 `score=null`、状态"未评估" |
| 语言模型问答服务 | 由 H08 提供，T10 已接线 | 王宏锦 | 配置 `LLM_PROVIDER` 后启用；未配置时结构化回答，引用仍可追溯 |
| 外部解析/分析服务对接 | 复用 `/analyses` 结构 | 王宏锦（王天一接入） | 当前用本地确定性实现（`local-rules-v1`），接入后接口不变 |

## 5. 接口交接约定

1. **稳定编码**：体检项目用 `exam_items.code`（大写、下划线），指标用
   `metric_dictionaries.metric_code`；未命中目录的导入指标以 `UNMAPPED` 占位并保留原文，
   由 T08 映射队列人工确认。方案、报告、导入任务与分析运行都返回稳定 ID 便于串联证据。
2. **契约先行**：新增字段先在本文件登记（字段名、类型、必填、含义、版本），再实现。
   王宏锦提出的存储字段由王天一落地迁移；服务配置由王天一接入全局配置。
3. **不伪造状态**：模型未接入时返回"未评估"；未知价格不参与总价计算；
   前端不得用本地计算替代后端费用、规则或模型输出；`score` 为空就是为空。
4. **状态必须可验证**：所有"已实现"条目以干净分支上的 OpenAPI 与测试为准。
5. **错误语义**：401（未登录/令牌失效）与 403（角色或归属不允许）严格区分；
   子资源不可见时返回 404，避免探测他人档案结构。
6. **兼容性**：既有 `/workflow/*`、`/prevention/*`、`/imports` 字段保持可读；新增字段只增不改；
   旧方案快照与旧修订继续可回看。
7. **版本与过期**：分析、方案、报告都返回 `stale` 与版本字段；资料变化后旧结果只读回看。
8. **扫描面**：开发环境开放 `/docs`；`APP_ENV=production` 时关闭 `/docs`、`/redoc`、`/openapi.json`。

## 6. 待确认项

| # | 事项 | 影响 | 需要的决定 |
| --- | --- | --- | --- |
| 1 | T01—T12 九个 PR 的合并顺序 | 合并前所有业务接口仍无鉴权 | 张家睿按 #30→#38 顺序审查合并；分支为叠加关系 |
| 2 | `auth_required` 何时切为 true | 前端 C01 未就绪时会被 401 拦住 | 陈子正给出 C01 完成时间，王天一同步切开关（本地开发保持 false） |
| 3 | 导入任务异步化 | 当前同步解析，单进程串行处理 | 与陈子正、王宏锦在 M1 前确认是否需要 worker |
| 4 | 分析发现来源切换 | 影响 T04/T05 的输入 | H 系列服务合并后由王天一接线（接口不变） |
| 5 | 报告模板细节 | 机构抬头、页眉页脚 | 与陈子正确认机构格式 |

## 变更记录

- 2026-09-20 首版：登记 T01 接口、M1 资源清单与权限矩阵。
- 2026-09-20 修订（响应复审意见）：把"已实现"改为以干净 `main` 的 OpenAPI 为准；T01 移入
  "已在未合并分支实现"；价格、导入、分析、管理、报告、问答等单列"计划中"。
- 2026-09-21 修订：T01—T12 全部实现并进入 PR 队列；第 3 节登记各任务分支与合并顺序，
  第 4 节收敛为仍需外部数据/服务的三项；补充鉴权、过期、生产文档开关等约定。
