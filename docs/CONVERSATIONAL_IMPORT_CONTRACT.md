# 对话式体检档案管理：后端接口契约（AI-T01）

日期：2026-09-21。负责人：王天一（后端）、陈子正（前端）。
状态：**后端实现完成（AI-T01–AI-T08 后端部分）、自动化测试通过；联合验收与真实模型记录待完成。**

本契约对应任务书 [TASK_WTY_CONVERSATIONAL_IMPORT.md](TASK_WTY_CONVERSATIONAL_IMPORT.md)。
接口使用 JSON，但下列技术字段**不直接展示给用户**：档案 ID、会话 ID、稳定记录 ID、
草稿/已确认状态、档案版本、消息 ID、操作 ID、待确认动作、缺项、待追问问题、
实际变更摘要、服务状态、分析是否过期、分系统可用状态。

## 1. 范围与职责

- 后端：会话/草稿/档案持久化、模型对话编排、白名单动作校验与事务执行、规划联动、迁移、测试。
- 前端：对话组件、人体点亮、历史详情、规划页、新建档案交互（`frontend/` 由陈子正实现）。
- 复用现有 `smart-import` 提取能力与 `prevention` 评估能力，不重做 OCR、不训练模型。
- 本轮只覆盖心血管、血糖与代谢、肾功能相关资料字段（同现有 `PreventionRequest` 字段集）。

### 1.1 不提供 / 明确不做的能力

- 无直接编辑表格、JSON 导入导出、公开示例入口；原文依据不新增持久化，也不在前端展示。
- 无模型生成的疾病概率或新医疗结论；模型只提“白名单动作”，由服务端校验后执行。
- 不新增对外 Ollama 或公网部署要求；不扩大为通用医疗问诊。
- 删除后档案不能为空（至少保留一条检查记录）；同日只能保留一条已确认记录（沿用现有输入校验）。

## 2. 领域对象与技术字段（不直接展示给用户）

| 字段 | 说明 |
| --- | --- |
| `profile_id` | 独立体检档案 ID（UUID 字符串）。一个人一份，禁止跨人自动合并。 |
| `display_name` | 当前档案显示名称（前端“当前档案”入口使用），例如“体检档案 2026-09-21”“第二位体检人”。 |
| `session_id` | 会话 ID。新建档案或“重新开始整理”都会生成新会话。 |
| `record_id` | 稳定记录 ID（`v-xxxxxxxx`）：从草稿创建起固定，不依赖列表顺序。 |
| `message_id` / `user_message_id` | 消息 ID，用于回放与幂等。 |
| `op_id` | 操作 ID（幂等键，客户端生成，1–80 字符）。所有写操作必填。 |
| `pending_action_id` | 待确认/待追问动作 ID。 |
| `draft_version` | 草稿版本：草稿每次变更 +1。 |
| `version` | 档案已确认版本：确认/修改/删除/撤销生效 +1；仅改草稿不改变。 |
| `snapshot_version` | 规划快照对应的档案版本。 |

### 2.1 数据状态

- 草稿（`draft`）：未确认的结构化数据，只用于对话展示；不点亮人体、不影响规划。
- 已确认资料（`confirmed_data`）：通过服务端校验后的事务性写入，参与点亮与规划。
- 快照（`current_snapshot` / `plans`）：不可变评估报告，`status=current` 为最新，
  被新版本覆盖后置 `stale`，仍可按档案只读回看。

### 2.2 保留边界

- 持久化：聊天内容、结构化草稿、已确认资料、待处理动作、操作日志、规划快照。
- 原始上传文件/附件：沿用现有 smart-import 边界仅内存处理，不写入会话数据库。
- 原文依据：只在模型调用期使用，不长期保存、不在前端展示。

## 3. 状态模型

### 3.1 档案数据状态

```
草稿(未确认) ──确认(校验通过)──> 已确认(version+1)
    │                                │
    └─修改/删除(仅草稿, version 不变)  └─修改/删除/撤销(version+1)
```

- 确认时草稿合并进已确认资料：**新增记录追加，不覆盖其他年份记录**（验收 3）。
- 已确认资料的任何修改都先做整体一致性校验（日期/年龄、病史、单位、范围），
  不通过则“解释原因 + 保留原记录”，不写入（验收 8）。
- `analysis_stale`：已确认资料变更后，若该档案存在规划快照则置为 `true`（快照同时置 `stale`）；
  档案还没有任何快照时不虚报过期。

### 3.2 待确认动作生命周期

```
open ──> resolved（用户回答/确认后执行）
  │──> cancelled（用户取消）
  │──> expired（“重新开始整理”时失效）
```

字段级追问保存在 `profile_drafts.questions`（由缺项确定性生成），
动作级追问保存在 `pending_actions`（`delete_confirm` / `choose_record` / `choose_field` /
`choose_unit` / `duplicate_date` / `model_question`）。

新建档案时**不**清除旧档案的待处理动作：它们仍绑定旧档案，只作用于旧档案，
并遵守旧档案的确认与版本校验（验收 18：旧待确认动作不能对新档案生效）。

### 3.3 快照生命周期

```
current（最新，指向 version N）──新版本确认/修改/重规划──> stale（只读回看）
```

### 3.4 撤销

- 只支持**最近一次**成功的数据修改或软删除；撤销后撤销上下文清空，避免连环回退。
- 撤销本身是一次真实变更：`version+1`，旧快照保持 `stale`，需要重新生成规划。
- 删除为软删除（记录进入 `confirmed_data.deleted` 并保留 `deleted_at`），可撤销恢复。

## 4. 端点总览（前缀 `/api/v1/prevention/conversation`）

| 方法 | 路径 | 用途 | `op_id` |
| --- | --- | --- | --- |
| GET | `/status` | 模型与服务状态（导入区提示） | — |
| GET | `/profiles` | 档案列表（切换/回看入口，含 `display_name`） | — |
| POST | `/profiles` | 新建用户档案（AI-T08） | 必填 |
| GET | `/profiles/{profile_id}/state` | 恢复当前档案完整状态 | — |
| POST | `/profiles/{profile_id}/messages` | 发送文字/附件，驱动对话 | 必填 |
| POST | `/profiles/{profile_id}/confirm` | 显式确认当前草稿 | 必填 |
| POST | `/profiles/{profile_id}/restart` | 重新开始整理（保留已确认与规划） | 必填 |
| POST | `/profiles/{profile_id}/plan` | 基于当前已确认版本生成/重新生成规划 | 必填 |
| GET | `/profiles/{profile_id}/plans` | 快照列表（标注版本/过期） | — |
| GET | `/profiles/{profile_id}/plans/{snapshot_id}` | 快照详情（只读回看） | — |

### 4.1 统一状态字段（`state` 与消息响应共有）

```json
{
  "profile_id": "…", "display_name": "体检档案 2026-09-21", "session_id": "…",
  "version": 1, "draft_version": 3,
  "confirmed_data": null, "draft": null,
  "messages": [{"message_id": "…", "role": "user|assistant", "text": "…",
                "created_at": "…", "changed_summary": [], "attachment": null}],
  "pending_actions": [{"action_id": "…", "action": "delete_visit", "field": null,
                       "record_id": "v-1", "question": "…", "candidates": null,
                       "purpose": null}],
  "missing": ["visits.v-1.smoking"], "questions": ["…"],
  "unknowns": ["visits.v-1.smoking"],
  "capabilities": ["心血管：已有资料，暂不能计算 —— 缺少：当前吸烟"],
  "system_availability": {"cardiovascular": false, "glucose_metabolism": true,
                          "renal": true},
  "system_status": {"cardiovascular": {"has_data": true, "calculable": false,
                                       "notes": ["缺少：当前吸烟"]}, "…": {}},
  "system_history": {"cardiovascular": {"label": "心血管",
                                        "points": {"sbp": [{"date": "2025-09-20",
                                                            "value": 138,
                                                            "record_id": "v-1"}]}}},
  "analysis_stale": false,
  "current_snapshot": {"snapshot_id": "…", "snapshot_version": 1, "status": "current",
                       "created_at": "…", "planning_window": ["…", "…"],
                       "recommendation_count": 5},
  "service_state": "ready"
}
```

消息响应额外包含：

```json
{"message_id": "…", "user_message_id": "…", "reply": "……",
 "changed_summary": [{"action": "update_visit", "record_id": "v-1", "field": "sbp",
                      "value": 152, "unit": "mmHg", "scope": "confirmed",
                      "converted": false}],
 "rejected_actions": [{"field": "sbp", "reason": "收缩压 500 超出可接受范围 60–260，原记录保持不变。"}]}
```

- `missing` 采用**稳定记录 ID 路径**：`visits.<record_id>.<field>`（不是列表下标），
  删除或重排记录后仍可定位；档案级字段直接是 `sex`、`known_cvd` 等。
- `changed_summary` 是服务端实际写入的变更；`reply` 只是自然语言说明，
  **模型说“已修改”不作为成功依据**。
- `capabilities` 区分“有资料”（`system_availability`）与“可以计算”（`system_status.*.calculable`）。

## 5. 端点详细定义

### 5.1 GET `/status`

```json
{"service_state": "ready | model_unavailable", "ready": true,
 "model": "qwen3-vl:4b-instruct", "message": "本地模型已就绪"}
```

### 5.2 POST `/profiles`（新建用户档案 / 工作区切换，AI-T08）

请求：

```json
{"op_id": "op-2026-09-21-001", "display_name": "第二位体检人",
 "save_current": {"profile_id": "当前档案ID", "save": "yes | no | cancel"}}
```

- `save=yes`：先为当前档案生成规划快照，成功后才新建；失败返回 `400 save_failed`
  且当前工作区完全不变（验收 16）。当前档案还没有已确认资料时视为“无规划可保存”，
  不阻塞新建。
- `save=no`：直接新建；只放弃当前页面未保存的工作区内容，不删除旧档案快照。
- `cancel`：返回当前档案原状态（`created=false`, `cancelled=true`），不新建、不改动。
- 幂等：同一 `(来源档案, op_id)` 重复请求返回第一次结果，不产生多个档案（验收 18）。
- `display_name` 省略时自动生成“体检档案 YYYY-MM-DD”，重名自动加序号。

响应 `201`（拒绝时为 `400`）：

```json
{"profile_id": "p-new", "display_name": "第二位体检人", "session_id": "s-new",
 "version": 0, "draft_version": 0, "confirmed_data": null, "draft": null,
 "messages": [], "pending_actions": [], "missing": [], "questions": [], "unknowns": [],
 "capabilities": ["当前没有已确认资料；草稿不会点亮人体，也不参与规划。"],
 "system_availability": {"cardiovascular": false, "glucose_metabolism": false,
                         "renal": false},
 "system_status": {"cardiovascular": {"has_data": false, "calculable": false,
                                      "notes": ["缺少：…"]}, "…": {}},
 "system_history": {"cardiovascular": {"label": "心血管", "points": {"sbp": []}}, "…": {}},
 "analysis_stale": false, "current_snapshot": null, "service_state": "ready",
 "created": true, "cancelled": false}
```

前端新建后应清空：人体（0/3 未点亮）、历史详情、规划、聊天、附件、草稿、待确认动作、
撤销上下文、浏览器缓存；旧档案的已保存资料与快照保持原样，可从“已保存规划”按档案只读回看。

### 5.3 GET `/profiles/{profile_id}/state`

返回 4.1 的完整结构（当前会话最近 50 条消息）；档案不存在返回 `404 not_found`。
刷新页面或重启后端后用它恢复档案、对话、草稿与待回答问题（验收 9）。

### 5.4 POST `/profiles/{profile_id}/messages`（核心对话入口）

请求：

```json
{"op_id": "msg-0001", "text": "粘贴的资料正文或对追问的回答",
 "file": {"name": "报告.pdf", "content": "<base64>"},
 "expected_version": 1}
```

服务端处理顺序（全部在一个事务内完成）：

1. 幂等检查 `(profile_id, op_id)`；命中则原样返回首次结果。
2. 校验 `expected_version`（不匹配 → `409 version_conflict`，附 `current_version`）。
3. **附件消息**：整条消息只作为资料，调用现有提取能力，结果只进草稿；
   附件正文里的“删除/忽略指令”等文字无法变成动作（验收 10）。
4. 存在动作级待确认/待追问时，先尝试把消息解析为该动作的答案（确定性解析）。
5. 明确的指令走确定性路径：撤销 / 删除 / 修改 / 单位纠正 / 确认 / 取消。
6. 存在字段级追问且消息不像资料正文时，用本地模型兜底理解自由表达；
   模型只能返回白名单动作，非法输出 → `422 invalid_model_output`（整体不写入）。
7. 其余文字按“资料正文”处理，复用现有提取能力（含原文依据校验），只写草稿。

响应见 4.1；`reply`/`changed_summary`/`rejected_actions` 如实反映服务端结果。

**没有执行依据时不会执行**：目标不唯一先追问；“未提及”不会当成“否”；
模型离线/超时/输出非法时不写入、也不返回虚假成功（验收 1/4/5/7/10）。

### 5.5 POST `/profiles/{profile_id}/confirm`

```json
{"op_id": "op-confirm-1", "expected_version": 1}
```

- 草稿按 `PreventionRequest` 规则整体校验（必填、日期、年龄一致、病史一致、同日重复、越界）。
- 校验失败 → `422 validation_failed`，附 `errors` 与 `missing`，草稿原样保留、不写库。
- 被明确标记“不知道”的必填项**不会用默认值代替**：确认返回 `422` 并列出受限字段（验收 2）。
- 成功：草稿合并入已确认资料，`version+1`，存在快照时置 `stale` 并设 `analysis_stale=true`。

### 5.6 POST `/profiles/{profile_id}/restart`（重新开始整理）

清空本轮未确认的文字/附件/草稿/待执行动作/撤销上下文，开启新会话；
保留当前档案的已确认资料、版本与已保存规划。与“新建用户档案”是两种不同操作（验收 19）。

### 5.7 POST `/profiles/{profile_id}/plan`

基于当前已确认版本重新评估（复用 `prevention.assess`）；旧 `current` 快照置 `stale`，
新快照 `snapshot_version = version`。资料不足时返回 `422 validation_failed`
并给出 `missing`/`capabilities`，不补默认值强行计算（验收 13）。

响应 = 快照内容 + 元数据：

```json
{"snapshot_id": "…", "snapshot_version": 2, "status": "current",
 "profile_id": "…", "display_name": "…", "version": 2, "analysis_stale": false,
 "input": {}, "risk": {}, "blockers": [], "planning_window": ["…", "…"],
 "recommendations": [{"code": "kidney", "systems": ["renal", "glucose_metabolism"],
                      "related_systems_note": "同时涉及血糖与代谢（糖尿病病史）",
                      "due_date": null, "…": "…"}],
 "overall": [{"code": "kidney", "deduplicated": false, "…": "…"}],
 "scope_index": {"cardiovascular": ["bp", "lipids"], "glucose_metabolism": ["glucose"],
                 "renal": ["kidney"]},
 "system_labels": {"cardiovascular": "心血管", "…": "…"},
 "trends": [], "sources": {}, "limitations": [], "review_status": "待医学审核"}
```

- `systems` 是稳定归属字段；同一建议跨系统时整体结果 `overall` 去重并保留关联说明（验收 13）。
- 分系统页用 `scope_index` 过滤，整体页用 `overall`；两者来自同一快照，不重复计算。
- 规则未给确定时间时 `due_date` 为 `null`，前端显示“未定”，模型不得编造日期。

## 6. 错误码与业务状态

| HTTP | `error` | 含义 | 前端映射 |
| --- | --- | --- | --- |
| 400 | `invalid_input` | 请求格式/字段非法（含 `save_failed`） | 导入区错误提示 |
| 404 | `not_found` | 档案/快照不存在 | 返回档案列表 |
| 409 | `version_conflict` | 基于过期版本的操作 | “内容已被更新，请重新核对”（附 `current_version`） |
| 409 | `duplicate_date` | 同日重复记录（作为 `pending_actions` 返回，一般不是 HTTP 错误） | 解释并要求选择处理方式 |
| 422 | `validation_failed` | 草稿/已确认资料校验失败（附 `errors`、`missing`） | 展示缺项/冲突说明 |
| 422 | `invalid_model_output` | 模型输出非法或含未白名单动作 | “请重试” |
| 429 | `processing` | 单 worker 正在处理另一请求 | “正在处理中” |
| 503 | `model_unavailable` | 模型未就绪/离线 | “模型未就绪” |
| 504 | `timeout` | 模型处理超时 | “处理超时，请重试” |

重试规则：除 `validation_failed`/`version_conflict` 外，前端可携带**相同 `op_id`** 重试，
服务端幂等返回第一次结果；超时、非法模型输出、取消都不会产生半完成写入。

## 7. 幂等、版本与并发

- 所有写操作必须携带 `op_id`；服务端以 `(profile_id, op_id)` 去重并保存首次响应。
- 每次消息处理是单事务：动作全部通过校验才提交，异常整体回滚。
- 携带 `expected_version` 的请求在版本不匹配时返回 `409`，前端应重新拉取 `state`，
  禁止覆盖新版本（验收 11）。
- 不同标签页/不同档案互不影响：任何写入都只针对 URL 中的 `profile_id`，
  迟到响应不会写入其他档案（验收 18/19）。

## 8. 前端调用顺序

### 8.1 主流程（上传 → 追问 → 回答 → 确认 → 点亮 → 规划 → 修改 → 重规划）

1. `GET /status`：未就绪时在导入区提示，不假装成功。
2. 首次进入：`GET /profiles`；无档案时 `POST /profiles` 建立空工作区。
3. `POST messages`（文字或附件）→ 返回 `draft`、`missing`、`questions`。
4. 有 `questions` 或 `pending_actions` 时逐条回答（继续 `POST messages`）。
5. 用户确认（对话中说“确认”或直接 `POST confirm`）→ `version+1`，
   `system_availability` 变为可点亮集合。
6. `POST plan` 生成规划（`current` 快照）；刷新用 `GET state` 恢复，`GET plans` 回看。
7. 修改/删除 → `POST messages` → 旧快照置 `stale`（`analysis_stale=true`）→ 重新 `POST plan`。
8. 历史详情用 `confirmed_data` + `system_history`；人体点亮用 `system_availability`；
   详情页“无法计算/缺项”用 `system_status` + `capabilities`。

### 8.2 新建用户档案（AI-T08）

1. 用户点“＋ 新建档案”→ 弹窗：“先保存当前规划？”【先保存】【不保存继续】【取消】。
2. 【取消】→ `POST /profiles {save_current:{profile_id, save:"cancel"}}`（或前端直接不发请求），
   页面状态不变。
3. 【先保存】→ `POST /profiles {save:"yes", profile_id}`；服务端先保存当前规划再新建。
   `400 save_failed` 时留在当前档案并提示。
4. 【不保存继续】→ `POST /profiles {save:"no", profile_id}`。
5. 新建成功：用返回的 `profile_id`/`session_id` 清空页面；旧快照仍可按档案只读回看。
6. 处理中的上传/识别/确认/规划请求必须绑定发起时的 `profile_id`+`session_id`+`version`；
   切换后丢弃其响应（服务端不会把它们写到新档案）。

### 8.3 与“重新开始整理”的区别

| 操作 | 清空 | 保留 | 档案 ID |
| --- | --- | --- | --- |
| 重新开始整理 `POST restart` | 草稿、附件、待执行动作、撤销上下文、对话上下文 | 已确认资料、版本、已保存规划 | 不变 |
| 新建用户档案 `POST /profiles` | 同上，且页面整体清空（人体 0/3、历史/规划空态） | 旧档案全部保留（新档案为空） | 新建 |

## 9. 分系统状态与点亮规则（0/3 人体）

`system_availability` 三系统：`cardiovascular`（心血管）、`glucose_metabolism`（血糖与代谢）、
`renal`（肾功能）。

- “有资料”（点亮）= 最新已确认记录具备该系统必需字段：
  心血管 `sbp`/`total_c`/`hdl_c`/`bmi`；血糖与代谢 `fasting_glucose`/`hba1c`/血糖结论；肾功能 `egfr`。
- “可以计算”（`system_status.*.calculable`）= 资料完整且通过 `PreventEquations` 输入范围与
  365 天时效检查；否则在 `notes` 中说明原因（缺项、明确“不知道”、超出模型范围、记录过旧）。
- 人体点亮代表“相关资料已确认”，不代表健康、疾病或风险结论。
- 详情页三个来源：`confirmed_data`（历史记录）、`system_history`（分系统指标序列）、
  `system_status`/`capabilities`（可用能力与受限原因）、`analysis_stale`（规划是否需要重算）。

## 10. 持久化与保留边界

新增表（迁移 `a7c3d5e91b02_conversational_profiles`，不改动旧表）：
`profiles`、`profile_drafts`、`conversation_sessions`、`conversation_messages`、
`pending_actions`、`action_logs`、`archive_snapshots`。

- `profiles.confirmed`：已确认资料（JSON，含 `record_id`、`unknowns`、软删除记录 `deleted`）。
- `action_logs`：幂等键、真实响应、撤销上下文（`before`）；撤销链不跨档案。
- `archive_snapshots`：与档案版本绑定的评估快照，不冒充最新结果。

## 11. 示例

### 11.1 成功闭环

```text
POST messages {op_id:"m1", text:"2026-09-20 体检：男，56岁，血压 138/85，总胆固醇 5.2 mmol/L，HDL 1.3，BMI 26，eGFR 88，空腹血糖 5.8。无糖尿病、不吸烟、未用降压药和他汀。"}
→ 200 reply:"已加入待核对记录：2025-09-20。还需要补充：已确诊心血管疾病？…"
   draft_version:1 missing:["known_cvd","pregnant","symptomatic"]

POST messages {op_id:"m2", text:"没有心血管疾病，未妊娠，无不适"}
→ 200 missing:[] questions:[] version:0

POST confirm {op_id:"m3", expected_version:0}
→ 200 version:1 system_availability:{cardiovascular:true, glucose_metabolism:true, renal:true}
   analysis_stale:false

POST plan {op_id:"m4", expected_version:1}
→ 200 snapshot_id:"…" snapshot_version:1 recommendations:[…] overall:[…]
```

### 11.2 缺项追问与“不知道”

```text
POST messages {op_id:"m5", text:"…（未写吸烟与胆固醇单位）"}
→ 200 questions:["…当前吸烟？请回答：是 / 否 / 不知道","胆固醇的单位是 mmol/L 还是 mg/dL？"]
   missing:["visits.v-1.smoking","visits.v-1.chol_unit"]

POST messages {op_id:"m6", text:"吸烟状态不知道"}
→ 200 changed_summary:[{action:"unknown_explicit", field:"smoking", record_id:"v-1"}]
   reply:"已把当前吸烟记为“不知道”…受限能力：无法计算心血管长期风险（PREVENT 需要当前吸烟状态）。"
   questions:[]   // 不再循环追问

POST confirm {op_id:"m7"} → 422 validation_failed（不能用默认值代替“不知道”）
```

### 11.3 冲突：同日重复与版本冲突

```text
POST messages {op_id:"m8", text:"2025-09-20 空腹血糖 6.2"}   // 同日已有记录
→ 200 pending_actions:[{action:"duplicate_date",
   question:"2025-09-20 已经有一条记录（编号 v-1）。请选择：覆盖该记录 / 保留原记录 / 放弃新资料。"}]

POST confirm {op_id:"m9", expected_version:0}   // 实际已是 1
→ 409 version_conflict {current_version:1, expected_version:0}
```

### 11.4 删除、取消与撤销

```text
POST messages {op_id:"m10", text:"删除去年的记录"}
→ 200 pending_actions:[{action:"delete_visit", record_id:"v-2",
   question:"确认删除这条记录吗？2025-09-19（…，编号 v-2）。确认后才执行，删除后仍可撤销。"}]
   // 确认前没有任何删除

POST messages {op_id:"m11", text:"算了，不删了"} → changed_summary:[{action:"cancel"}]
POST messages {op_id:"m12", text:"确认删除"} → changed_summary:[{action:"delete_visit", soft:true}]
   version+1, analysis_stale:true
POST messages {op_id:"m13", text:"撤销"} → changed_summary:[{action:"undo"}]，记录恢复，version+1
```

### 11.5 单位纠正与换算

```text
// 只改标签（数值本来就是 mg/dL，标签写成 mmol/L）：
POST messages {op_id:"m14", text:"胆固醇单位写错了，是 mg/dL"}
→ 200 changed_summary:[{action:"update_visit", field:"chol_unit", value:"mg/dL",
   converted:false}]

// 标签改错会与数值矛盾时拒绝并解释：
POST messages {op_id:"m15", text:"胆固醇单位写错了，是 mg/dL"}   // 数值是 5.2 mmol/L
→ 200 rejected_actions:[{field:"chol_unit",
   reason:"改成该单位后数值不一致：总胆固醇 5.2 在 mg/dL 下不在 40–600 的合理范围…原记录保持不变。"}]

// 换算数值（一次性，不二次换算）：
POST messages {op_id:"m16", text:"总胆固醇 200 mg/dL"}   // 记录单位 mmol/L
→ 200 changed_summary:[{action:"update_visit", field:"total_c", value:5.172,
   unit:"mmol/L", converted:true, basis:"mg/dL → mmol/L 换算一次…"}]
```

### 11.6 取消 / 超时 / 模型离线 / 非法输出

```text
POST messages → 504 {error:"timeout"}；相同 op_id 重试 → 幂等返回首次结果
POST messages → 503 {error:"model_unavailable"}；GET state 仍可查看已保存内容
POST messages → 422 {error:"invalid_model_output"}；不写入任何动作
POST messages（另一 worker 正在处理）→ 429 {error:"processing"}
```

## 12. 与陈子正的对接清单（待确认/需前端实现）

前端需要接入的字段与状态（后端已提供）：

1. **当前档案入口**：`display_name` + `profile_count`（`GET /profiles` 可用于切换/回看）。
2. **空态**：新档案 `system_availability` 全 `false`（人体 0/3）、`confirmed_data=null`、
   `messages=[]`、`current_snapshot=null`。
3. **导入区提示**：`service_state`（`ready`/`model_unavailable`）与 429/503/504/422 错误码。
4. **待办气泡**：`questions`（字段级）与 `pending_actions[].question`（动作级，含 `candidates`）。
5. **历史详情**：`confirmed_data.visits[]`（含 `record_id`）+ `system_history.points`。
6. **点亮/可用能力**：`system_availability`（点亮）与 `system_status`/`capabilities`（能否计算）。
7. **规划过期提示**：`analysis_stale`；重算入口绑 `expected_version`。
8. **只读回看**：`GET plans` / `GET plans/{id}` 返回 `read_only`、`is_latest_version`、
   `display_name`，仅回看不改变当前编辑对象。

仍建议双方确认的 UI 细节：

1. 消息交互方式：单请求-响应（模型较慢，建议按钮态 + 超时提示，不做流式）。
2. 新建档案弹窗三步文案与归属（前端负责样式，服务端语义见 5.2/8.2）。
3. 三个分系统与插画部位的对应关系（字段映射见第 9 节）。
4. 快照只读回看的入口位置（历史详情页内或独立列表）。
5. 附件上传是否分片/压缩（服务端沿用 8 MB、PDF ≤5 页、文本 ≤16000 字符的现有边界）。

### 12.1 与初版契约的差异（已在实现中确定）

1. 同日重复的处理选项为**覆盖 / 保留原记录 / 放弃新资料**；不提供“另存为新记录”，
   因为现有输入校验规定同一天只能保留一条已确认记录，另存只会在确认阶段失败。
2. `missing` 使用 `visits.<record_id>.<field>` 而不是列表下标，保证删除/重排后仍可定位。
3. 新增 `GET /profiles`（档案列表）供切换与回看入口使用。
4. `restart` 会失效本档案待执行动作；**新建档案不会**（避免影响仍在操作旧档案的标签页）。
5. `analysis_stale` 只在存在规划快照时才置为 `true`（没有规划就谈不上“过期分析”）。
6. 撤销是单步窗口：撤销后撤销上下文清空，避免连环回退把档案回退成空。
7. 明确“不知道”的必填项会阻止确认（返回 422 并说明受限能力），不用默认值强行计算。

## 13. 已知限制

- 单 worker 串行处理（同 smart-import），忙时返回 429；不做流式输出。
- 确定性解析覆盖常见中文写法；表达过于自由时依赖本地模型的兜底理解。
- 撤销仅支持最近一次数据修改/软删除；跨版本、跨档案撤销不成立。
- 不训练模型、不改变 PREVENT 方程或现有医学规则含义；建议仍标记“待医学审核”。
- 前端联合验收与真实本地模型记录见第 14 节状态。

## 14. 实现与验收状态

### 14.1 AI-T01 – AI-T08 后端状态

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| AI-T01 接口契约 | 完成 | 本文档即契约；实现与文档已核对一致 |
| AI-T02 持久会话与草稿 | 完成 | 7 张新表 + 迁移；刷新/重启后 `GET state` 恢复；档案隔离 |
| AI-T03 缺项追问与人工核对 | 完成 | 确定性生成缺项与追问；“不知道”记录为未知并说明受限能力 |
| AI-T04 对话驱动档案操作 | 完成 | 新增/修改/删除/取消/撤销；按年份、日期、编号定位；不默认最新一条 |
| AI-T05 受控执行与一致性 | 完成 | 白名单动作 + 事务提交 + 幂等 + 版本校验 + 软删除与撤销 |
| AI-T06 历史、点亮与规划 | 完成 | `system_availability`/`system_status`/`system_history`；快照 stale 与重算 |
| AI-T07 运行与降级 | 完成 | 503/504/429/422 明确状态；失败不产生半完成写入 |
| AI-T08 新建档案与切换 | 完成（后端） | `POST /profiles` 三选项、幂等、空态字段、档案隔离 |

自动化测试：`backend/tests/conversation/`（解析器、对话闭环、档案切换、接口契约）。
共 78 项：`test_parser.py` 25、`test_conversation_flow.py` 28、`test_profiles.py` 14、
`test_api_contract.py` 11。运行方式：`cd backend && python -m pytest tests/conversation -q`。
全量后端测试与 Ruff 静态检查见 PR 说明。

### 14.2 待完成（需团队/环境）

- 与陈子正的真实页面联调（验收 14）。
- 真实本地模型记录（型号、输入、耗时、追问、实际数据库变化）：使用
  `backend/scripts/smoke_conversation.py`（需本机 Ollama + 已安装模型）执行并归档输出。
- 验收 10 的“上传文字要求删除记录”在真实模型下的复核（自动化测试已用模拟输出覆盖）。

## 15. 2026-09-22 审核复核后的契约变更（前端必读）

本轮修复了"旧确认请求可确认新草稿"和"对话接口没有账号归属"两个 P1 问题，
前端接入时按以下契约实现：

1. **确认必须携带草稿版本**：`POST /profiles/{id}/confirm` 的
   `expected_draft_version` 为**必填**字段，值取最近一次 `GET state` 返回的
   `draft_version`。若期间草稿被其它请求推进，服务端返回 **409**
   `version_conflict`，响应含 `current_draft_version` 与 `expected_draft_version`，
   前端必须提示"内容已更新，请重新核对"并刷新页面，不得重试同一版本。
2. **会话绑定**：`messages`/`confirm`/`restart`/`plan` 可携带 `session_id`
   （取 `GET state` 的 `session_id`）。携带旧会话 id 的迟到请求返回 **409**，
   响应含 `current_session_id`；前端应丢弃该响应，不能写入当前工作区。
3. **鉴权与归属**：全部对话端点都需要 `Authorization: Bearer <token>`（与 T01 一致）；
   未登录返回 **401**，访问他人档案与不存在同样返回 **404**（不泄露是否存在）。
   `POST /profiles` 创建的档案自动归属当前账号，`GET /profiles` 只返回本账号档案。
4. **确认后清空与点亮**：人体点亮、系统历史与规划只认 `confirmed_data`；
   草稿版本变化不得改变已确认内容与已保存规划。

前端联调用例（与后端自动化测试一一对应，见 `backend/tests/conversation/test_review_fixes.py`）：

| 场景 | 期望 |
| --- | --- |
| 看到 draft_version=1 → 别处更新为 2 → 用 1 确认 | 409，提示重新核对，`confirmed_data` 不变 |
| 用当前 `draft_version` 确认 | 200，`confirmed_data` 等于该版本草稿内容 |
| `restart` 后旧会话再发消息 | 409，新会话无这条消息 |
| 账号 B 访问账号 A 的档案 | 404；`GET /profiles` 列表不含 A 的档案 |
| `AUTH_REQUIRED=true` 且匿名请求 | 401 |
