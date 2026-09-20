# InsightCheck 2.0 接口契约（V2_API_CONTRACT）

负责人：王天一（T01—T12）。版本：v2.0-draft-1，日期：2026-09-20。
状态：M0 实施交付物，随实现推进更新；**当前已实现的部分标注「已实现」，其余为「计划中」**，
计划中的条目在落地前不改动对外行为。

本文是前后端与解析/分析服务之间的统一约定。字段、路径与状态码以本文为准；三个人使用同一套
稳定编码，不各自造字段。与 [TEAM_TASKS_V2.md](TEAM_TASKS_V2.md) 冲突时以任务书为准。

## 1. 通用约定

| 项 | 约定 |
| --- | --- |
| 基础路径 | `/api/v1`（`settings.api_v1_prefix`） |
| 健康检查 | `GET /health`，不需要登录，用于部署探活 |
| 认证 | `Authorization: Bearer <token>`；`auth_required=true` 时业务接口必须携带 |
| 内容类型 | `application/json`；上传接口使用 `multipart/form-data` |
| 时间 | 日期 `YYYY-MM-DD`；时间戳 ISO 8601（UTC）；服务端统一按 UTC 存储 |
| 金额 | 整数最小单位（分）+ 三字母币种；禁止浮点金额 |
| 分页 | 查询参数 `offset`（≥0）与 `limit`（1—500，默认 100） |
| 错误格式 | `{"detail": "<中文说明>"}`；校验失败为 422（FastAPI 默认结构） |
| 幂等 | 客户端生成 `request_id`/`Idempotency-Key`，重复提交返回首次结果 |
| 版本策略 | 路径带 `/api/v1`；破坏性变更新增字段或新路径，不修改既有字段语义 |

### 状态码

| 码 | 含义 |
| --- | --- |
| 200 / 201 / 204 | 成功 / 已创建 / 已删除 |
| 400 | 请求本身不合法（例如管理员停用自己） |
| 401 | 未登录、令牌无效、会话过期或已退出 |
| 403 | 已登录但角色或档案归属不允许 |
| 404 | 资源不存在（不区分「不存在」与「无权」，避免探测） |
| 409 | 唯一性冲突、幂等冲突（同编号不同输入） |
| 422 | 参数/口令/业务规则校验失败 |
| 500 | 服务内部错误，响应不包含堆栈 |

### 权限模型

角色：`admin`（管理员）、`doctor`（医生）、`viewer`（只读）。

| 能力 | admin | doctor | viewer |
| --- | --- | --- | --- |
| 读取自己可见的档案、历史、方案、报告 | ✅（全部档案） | ✅（名下档案） | ✅（名下档案） |
| 新建/修改档案、录入记录、生成方案 | ✅ | ✅ | ❌（403） |
| 账号管理、字典/价格/规则管理 | ✅ | ❌（403） | ❌（403） |

档案归属：`patients.owner_account_id`。非管理员账号只能访问自己名下的档案；**历史无主档案
（`owner_account_id` 为空）默认只有管理员可访问**，需要时由管理员指定负责人。
未启用鉴权（`auth_required=false`，仅本地开发）时按匿名管理员处理，行为与 1.0 一致。

## 2. 账号与会话（T01，已实现）

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

### 请求与响应

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

```http
POST /api/v1/auth/accounts        # 仅管理员

{"username": "doctor-b", "password": "Doctor-B-Pass-2026!", "display_name": "医生 B",
 "role": "doctor"}
```

创建成功返回 201 与账号信息（**不含口令与摘要**）。规则与错误：

| 场景 | 状态码 | 说明 |
| --- | --- | --- |
| 用户名已存在 | 409 | `用户名已存在` |
| 用户名不匹配 `^[A-Za-z0-9._-]{3,64}$` | 422 | 中文名放 `display_name` |
| 口令不足 10 位或强度不够 | 422 | 至少两类字符，不允许全同字符 |
| 非管理员调用管理接口 | 403 | |
| 停用账号登录 | 403 | `账号已停用，请联系管理员` |
| 口令错误 / 用户不存在 | 401 | 两者返回同一提示，避免枚举账号 |
| 令牌无效、过期、已退出 | 401 | 响应带 `WWW-Authenticate: Bearer` |
| 管理员改自己的角色或停用自己 | 400 | 防止把系统锁死 |

安全约定：口令使用 PBKDF2-HMAC-SHA256（默认 210000 次迭代，盐 16 字节）派生，库内只存
摘要、盐与迭代次数；会话只存令牌 SHA-256 摘要，明文令牌仅登录响应出现一次；比较使用常量
时间函数；停用账号或重置口令立即失效其全部会话。

首次部署初始化管理员（口令不回显，支持 `XUNYING_ACCOUNT_PASSWORD` 环境变量注入）：

```bash
python -m alembic upgrade head
python -m app.cli create-admin --username admin --display-name 管理员
```

## 3. M1 资源清单与路径

「状态」列：**已实现**＝本轮代码可用；**计划中**＝契约先定、实现随后，前端可用契约夹具，
但验收必须切回真实接口。

| 资源 | 路径 | 方法 | 权限 | 负责人 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 账号与会话 | `/auth/*` | 见第 2 节 | 公开/登录/admin | 王天一 | 已实现 |
| 版本化目录（体检项目） | `/exam-items` | GET/POST/PATCH/DELETE | 读:登录；写:admin | 王天一 | 已实现（沿用 1.0） |
| 指标字典 | `/metric-dictionaries` | GET/POST/PATCH/DELETE | 读:登录；写:admin | 王宏锦提供字段，王天一落地 | 已实现（待扩展 value_type/来源） |
| 档案 | `/patients` | GET/POST/PATCH/DELETE | 读写按归属 | 王天一 | 已实现（含归属过滤） |
| 检查记录 | `/health-checks`、`/lab-metrics`、`/imaging-exams` | GET/POST/PATCH/DELETE | 读写按归属 | 王天一 | 已实现（待扩展定性/文字类型） |
| 工作台流程 | `/workflow/patients`、`/workflow/records` | GET/POST | 读写按归属 | 王天一 | 已实现 |
| 三档方案 | `/workflow/plans`、`/workflow/plans/{id}`、`/export`、`/explain` | GET/POST | 读写按归属 | 王天一 | 已实现（三档服务待整合进接口） |
| 价格目录 | `/exam-item-prices`（规划名） | GET/POST/PATCH | 读:登录；写:admin | 王天一 | 计划中（服务与表已实现，管理接口未接） |
| 导入任务与校对 | `/imports/*`（`/imports/tasks`、`/imports/tasks/{id}/preview`、`/confirm`） | GET/POST | 写需 doctor 以上 | 王天一 | 计划中（1.0 有 `/health-records` 批量导入） |
| 分析运行 | `/analyses`、`/analyses/{id}` | GET/POST | 读写按归属 | 王天一（调用 H 系列） | 计划中 |
| 规则与候选 | `/rule-engine/*`、`/recommendation-ranking/*` | GET/POST | 写需 admin | 王宏锦内容，王天一集成 | 部分已实现 |
| 管理接口 | `/admin/*` | GET/POST | admin | 王天一 | 计划中（T08） |
| 报告 | `/reports/{id}`、`/reports/{id}/pdf` | GET | 按归属 | 王天一 | 计划中（T09） |
| 问答 | `/qa/ask` | POST | 登录 | 王天一接线，王宏锦服务 | 计划中（T10） |
| 部署与健康 | `/health`、`/health/detail` | GET | 公开/admin | 王天一 | 部分已实现 |

## 4. 接口交接约定

1. **稳定编码**：体检项目用 `exam_items.code`（大写、下划线），指标用
   `metric_dictionaries.metric_code`；方案、报告、导入任务均返回 `request_id`/`trace_id`
   便于串联证据。
2. **契约先行**：新增字段先在本文件登记（字段名、类型、必填、含义、版本），再实现。
   王宏锦提出的存储字段由王天一落地迁移；王宏锦提出的服务配置由王天一接入全局配置。
3. **不伪造状态**：模型未接入时返回 `未评估` 等显式状态；未知价格不参与总价计算；
   前端不得用本地计算替代后端费用、规则或模型输出。
4. **错误语义**：401 与 403 严格区分；404 不区分「不存在/无权」，避免探测他人档案。
5. **兼容性**：既有 `/workflow/*` 字段保持可读；新增字段只增不改；旧快照继续可回看。
6. **扫描面**：`/docs`（OpenAPI）在开发环境开放；生产环境按 T11 关闭或加访问控制。

## 5. 待确认项

| # | 事项 | 影响 | 需要的决定 |
| --- | --- | --- | --- |
| 1 | `auth_required` 何时切为 true | C01 登录界面就绪后切换，否则前端会被 401 拦住 | 陈子正给出 C01 完成时间，王天一同步切开关 |
| 2 | 导入任务接口形态（异步队列 vs 同步解析） | 影响 C03 上传进度与重试交互 | 与陈子正、王宏锦在 M1 前确认 |
| 3 | 分析运行是否落独立表还是复用 `recommendations` | 影响 T04/T07 与能力任务注册 | 王天一提出方案，张家睿裁决 |
| 4 | 报告 PDF 生成方式（服务端渲染 vs 前端打印） | 影响 T09/C10 分工 | 与陈子正确认 |

变更记录：2026-09-20 首版，登记 T01 已实现的账号与会话接口、M1 资源清单与权限矩阵。
