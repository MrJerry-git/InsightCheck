# InsightCheck 2.0 接口契约（V2_API_CONTRACT）

负责人：王天一（T01—T12）。版本：v2.0-draft-2，日期：2026-09-20。

**本 PR 只交付本文档**，不含任何代码改动。文档中每一条接口都标注了它在 `main` 上的真实状态，
状态定义见第 0 节。

## 0. 交付状态与核对方式

状态只有三种，含义严格区分：

| 标签 | 含义 |
| --- | --- |
| **已实现（main）** | 已合入 `main`，在干净检出上可直接调用 |
| **已在未合并分支实现** | 代码存在但**尚未合入 `main`**，不能作为 `main` 现有能力；分支与依赖单独列出 |
| **计划中** | 尚未实现，只登记契约形态，落地前不对外承诺 |

核对方式（2026-09-20，干净 `main` 检出）：`git checkout origin/main` 后执行

```bash
cd backend && PYTHONPATH=. python -c "from app.main import create_app; print(len(create_app().openapi()['paths']))"
```

结果：**51 条路径**，清单见第 2 节。该清单里**没有** `/api/v1/auth/*`，配置中也没有鉴权开关，
`patients` 没有归属过滤——这些能力都在第 3 节列出的未合并分支里。

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

### 3.1 T01 账号、会话、角色与档案访问控制

依赖分支：**`feat/auth-access`**（王天一，从 `main` 建立）。状态：**尚未合入 `main`，也没有对应实现 PR**
（该分支仍在交付过程中，包含一次失败提交，将以干净提交重新推送）。在它合并之前：

- `main` 没有 `/api/v1/auth/*` 路由；
- `settings` 没有 `auth_required` 开关，业务路由也未挂载鉴权依赖；
- `patients` 表没有 `owner_account_id`，档案没有归属过滤。

分支上的接口设计（**待合并后才在 `main` 生效**）：

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/auth/login` | 公开 | 用户名 + 口令换取会话令牌 |
| POST | `/auth/logout` | 登录 | 退出；`all_sessions=true` 时失效该账号全部会话 |
| GET | `/auth/me` | 登录 | 当前账号信息 |
| POST | `/auth/password` | 登录 | 本人改口令，需当前口令；成功后其它会话失效 |
| GET | `/auth/accounts` | admin | 账号列表 |
| POST | `/auth/accounts` | admin | 创建账号 |
| PATCH | `/auth/accounts/{account_id}` | admin | 改显示名、角色、启停、重置口令 |
| POST | `/auth/accounts/{account_id}/password` | admin | 重置口令并失效该账号全部会话 |

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username": "doctor-a", "password": "Doctor-Pass-2026!"}
```

```json
{
  "token": "kK3f...（只返回一次）",
  "token_type": "Bearer",
  "expires_at": "2026-09-20T22:00:00Z",
  "account": {
    "id": "70a06660-5c37-4071-b2bd-7e47999382a9",
    "username": "doctor-a",
    "display_name": "医生 A",
    "role": "doctor",
    "is_active": true,
    "created_at": "2026-09-20T09:00:00Z",
    "last_login_at": "2026-09-20T10:00:00Z"
  }
}
```

规则与错误（同分支实现）：用户名重复 409；用户名不匹配 `^[A-Za-z0-9._-]{3,64}$` 或口令强度不足 422；
非管理员调用管理接口 403；停用账号登录 403；口令错误与用户不存在统一返回 401 以免枚举账号；
令牌无效/过期/已退出 401；管理员改自己角色或停用自己 400。

安全设计（同分支）：PBKDF2-HMAC-SHA256（默认 210000 次迭代、16 字节盐）派生口令，库内只存摘要、
盐与迭代次数；会话只存令牌 SHA-256 摘要；常量时间比较；停用账号或重置口令立即失效其全部会话。
首次部署用 `python -m app.cli create-admin --username admin` 初始化管理员（口令不回显）。

### 3.2 权限模型（随 T01 一起生效）

角色：`admin`（管理员）、`doctor`（医生）、`viewer`（只读）。

| 能力 | admin | doctor | viewer |
| --- | --- | --- | --- |
| 读取档案、历史、方案、报告 | ✅ 全部 | ✅ 名下 | ✅ 名下 |
| 新建/修改档案、录入记录、生成方案 | ✅ | ✅ | ❌ 403 |
| 账号管理、字典/价格/规则管理 | ✅ | ❌ 403 | ❌ 403 |

档案归属：`patients.owner_account_id`。非管理员只能访问自己名下档案；历史无主档案默认仅管理员可见。
未启用鉴权（`auth_required=false`，仅本地开发）时按匿名管理员处理，与 1.0 行为一致。

## 4. 计划中（未实现）

| 资源 | 规划路径 | 方法 | 权限 | 负责人 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 价格目录管理 | `/api/v1/exam-item-prices` | GET/POST/PATCH | 读:登录；写:admin | 王天一 | 服务与表已在 `main`（`services/pricing*.py`、迁移 `b7e4c1a920d3`），管理接口未实现 |
| 导入任务与校对 | `/api/v1/imports/tasks`、`/imports/tasks/{id}/preview`、`/imports/tasks/{id}/confirm` | GET/POST | 写需 doctor 以上 | 王天一 | `main` 现有同步导入（`/imports`、`/imports/validate`）不含队列与校对确认 |
| 分析运行 | `/api/v1/analyses`、`/analyses/{id}` | GET/POST | 读写按归属 | 王天一（调用 H 系列） | 需先确定是否新建表，见第 6 节 |
| 管理接口 | `/api/v1/admin/*`（字典映射、价格生效范围、规则草稿/启用/版本、模型任务状态、审计查询） | GET/POST/PATCH | admin | 王天一 | T08 |
| 报告 PDF | `/api/v1/reports/{id}`、`/reports/{id}/pdf` | GET | 按归属 | 王天一 | T09，PDF 生成方式待定 |
| 问答 | `/api/v1/qa/ask` | POST | 登录 | 王天一接线，王宏锦服务 | T10，问答不得直接改方案 |
| 部署健康明细 | `/api/v1/health/detail` | GET | admin | 王天一 | T11 |

## 5. 接口交接约定

1. **稳定编码**：体检项目用 `exam_items.code`（大写、下划线），指标用
   `metric_dictionaries.metric_code`；方案、报告、导入任务均返回 `request_id`/`trace_id` 便于串联证据。
2. **契约先行**：新增字段先在本文件登记（字段名、类型、必填、含义、版本），再实现。王宏锦提出的
   存储字段由王天一落地迁移；提出的服务配置由王天一接入全局配置。
3. **不伪造状态**：模型未接入时返回 `未评估` 等显式状态；未知价格不参与总价计算；前端不得用本地
   计算替代后端费用、规则或模型输出。
4. **状态必须可验证**：本文所有「已实现」条目都以干净 `main` 的 OpenAPI 为准；实现落在分支上时
   必须写明分支名与未合并状态，不得计入 `main` 现有能力。
5. **错误语义**：401 与 403 严格区分；404 不区分「不存在/无权」，避免探测他人档案。
6. **兼容性**：既有 `/workflow/*` 字段保持可读；新增字段只增不改；旧快照继续可回看。
7. **扫描面**：`/docs`（OpenAPI）在开发环境开放；生产环境按 T11 关闭或加访问控制。

## 6. 待确认项

| # | 事项 | 影响 | 需要的决定 |
| --- | --- | --- | --- |
| 1 | T01 实现分支何时申请合并 | 合并前所有业务接口仍无鉴权 | 王天一修完 `feat/auth-access`（去掉失败提交）后提 PR，张家睿审查 |
| 2 | `auth_required` 何时切为 true | C01 登录界面就绪后切换，否则前端会被 401 拦住 | 陈子正给出 C01 完成时间，王天一同步切开关 |
| 3 | 导入任务接口形态（异步队列 vs 同步解析） | 影响 C03 上传进度与重试交互 | 与陈子正、王宏锦在 M1 前确认 |
| 4 | 分析运行是否落独立表还是复用 `recommendations` | 影响 T04/T07 与能力任务注册 | 王天一提出方案，张家睿裁决 |
| 5 | 报告 PDF 生成方式（服务端渲染 vs 前端打印） | 影响 T09/C10 分工 | 与陈子正确认 |

## 变更记录

- 2026-09-20 首版：登记 T01 接口、M1 资源清单与权限矩阵。
- 2026-09-20 修订（响应复审意见）：把「已实现」改为以干净 `main` 的 OpenAPI 为准（51 条路径，
  按分组列出）；T01 账号/会话/角色/归属过滤移入「已在未合并分支实现」，写明依赖分支
  `feat/auth-access`、未合并状态与合并前 `main` 的实际行为；价格、导入、分析、管理、报告、问答
  等未实现能力单列「计划中」，并标注服务/表是否已在 `main`。
