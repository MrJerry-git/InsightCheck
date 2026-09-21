# 对话式体检档案管理：后端接口契约（AI-T01）

日期：2026-09-21。负责人：王天一（后端）、陈子正（前端）。状态：待确认，尚未实现。

本契约对应任务书 [TASK_WTY_CONVERSATIONAL_IMPORT.md](TASK_WTY_CONVERSATIONAL_IMPORT.md) 的 AI-T01。
接口可用 JSON，但下列技术字段不直接展示给用户：档案 ID、会话 ID、稳定记录 ID、
草稿/已确认状态、档案版本、消息 ID、操作 ID、待确认动作、缺项、待追问问题、
实际变更摘要、服务状态、分析是否过期、分系统可用状态。

## 1. 范围与职责

- 后端：会话/草稿/档案持久化、模型对话编排、白名单动作校验与事务执行、规划联动、迁移、测试。
- 前端：对话组件、人体点亮、历史详情、规划页、新建档案交互（`frontend/` 由陈子正实现）。
- 复用现有 `smart-import` 提取能力与 `prevention` 评估能力，不重做 OCR/模型训练。
- 本轮只覆盖：心血管、血糖与代谢、肾功能相关资料字段（同现有 `PreventionRequest` 字段集）。

### 1.1 不提供 / 明确不做的能力

- 无直接编辑表格、JSON 导入导出、原文依据展示（前端不展示，服务端校验保留）。
- 无模型生成的疾病概率或新医疗结论；模型只提“白名单动作”，由服务端校验后执行。
- 不新增对外 Ollama 或公网部署要求；不扩大为通用医疗问诊。

## 2. 领域对象与技术字段（不直接展示给用户）

| 字段 | 说明 |
| --- | --- |
| `profile_id` | 独立体检档案 ID（UUID 字符串）。一个人一份，禁止跨人自动合并。 |
| `session_id` | 会话 ID。同一档案可恢复；新建档案必须生成新 session_id。 |
| `record_id` | 稳定记录 ID：每条检查记录（visit）从草稿创建起固定，不依赖列表顺序。 |
| `message_id` | 消息 ID。每轮对话消息唯一，用于回放与幂等。 |
| `op_id` | 操作 ID（幂等键）。客户端对同一动作重复提交携带相同 op_id。 |
| `pending_action_id` | 待确认/待追问动作 ID。 |
| `draft_version` | 草稿版本：草稿每次变更 +1。 |
| `version` | 档案已确认版本：确认/撤销生效 +1；草稿修改不改变。 |
| `snapshot_version` | 快照（规划报告）对应的档案版本。 |

### 2.1 数据状态

- 草稿（draft）：未确认的结构化数据，只能用于对话展示，不点亮人体、不影响规划。
- 已确认资料（confirmed）：通过服务端校验后的事务性写入，参与规划与点亮。
- 快照（snapshot）：每次确认/重新规划生成的不可变评估报告，`current=true` 为最新，
  之后被新版本覆盖时标记 `stale`。

### 2.2 保留边界

- 聊天内容、结构化草稿、待确认动作、操作日志持久化到数据库。
- 原始上传文件/附件按现有 smart-import 边界仅内存处理，不写入会话数据库，不新增长期保存。
- 原文依据仅在模型调用期使用；前端不展示。

## 3. 状态模型

### 3.1 档案数据状态

```
草稿(未确认) ──确认(校验通过)──> 已确认(version+1, 旧快照置 stale)
    │                                │
    └─修改/删除(仅草稿, version 不变)  └─撤销(version+1) / 再修改(新草稿)
```

### 3.2 待确认动作生命周期

```
open ──> resolved（用户回答/确认后执行）
  │──> cancelled（用户取消）
  │──> expired（新建档案/重新开始时失效；超时后端保留但前端可重试）
```

### 3.3 快照生命周期

```
current（最新，指向 version N）──新版本确认/重规划──> stale（仍可只读回看）
```

### 3.4 消息状态

`received -> processing -> answered`（成功）；错误时返回业务状态码，
消息与已保存档案不受影响，重试不重复新增记录。

## 4. 端点总览（前缀 `/api/v1/prevention/conversation`）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/status` | 模型与服务状态（前端导入区提示） |
| POST | `/profiles` | 新建用户档案（工作区切换，AI-T08） |
| GET | `/profiles/{profile_id}/state` | 恢复当前档案完整状态（刷新/重启后继续） |
| POST | `/profiles/{profile_id}/messages` | 发送文字/附件，驱动对话（AI-T02/T03/T04） |
| POST | `/profiles/{profile_id}/confirm` | 显式确认当前草稿（AI-T03） |
| POST | `/profiles/{profile_id}/restart` | 重新开始整理（保留已确认，清空草稿上下文） |
| POST | `/profiles/{profile_id}/plan` | 基于当前已确认版本生成/重新生成规划（AI-T06） |
| GET | `/profiles/{profile_id}/plans` | 快照列表（只读回看，标注版本/过期） |
| GET | `/profiles/{profile_id}/plans/{snapshot_id}` | 快照详情（只读回看） |

统一响应技术字段：`profile_id`、`session_id`、`version`、`draft_version`、
`service_state`、`analysis_stale`、`system_availability`、`changed_summary`、
`pending_actions`、`questions`（待追问问题）、`missing`（缺项）。

## 5. 端点详细定义

### 5.1 GET `/status`

响应：

```json
{
  "service_state": "ready | model_unavailable | processing",
  "model": "qwen3-vl:4b-instruct",
  "ready": true,
  "message": "本地模型已就绪"
}
```

### 5.2 POST `/profiles`（新建用户档案）

请求：

```json
{
  "op_id": "op-2026-09-21-001",
  "save_current": {"profile_id": "p-xxx", "save": "yes | no | cancel"}
}
```

- `save=yes`：服务端先保存当前规划（生成快照），成功后才新建；失败返回 500 且当前工作区不变。
- `save=no`：明确不保存则只放弃未保存工作区内容，不删除旧档案已保存记录。
- `cancel`：等价于取消，返回当前档案原状态，不新建。
- 同一 `op_id` 重复提交返回第一次结果（幂等），不产生多个档案。

响应 201：

```json
{
  "profile_id": "p-new",
  "session_id": "s-new",
  "display_name": "新建档案 2026-09-21",
  "version": 0,
  "draft_version": 0,
  "confirmed_data": null,
  "draft": null,
  "messages": [],
  "pending_actions": [],
  "missing": [],
  "questions": [],
  "system_availability": {"cardiovascular": false, "glucose_metabolism": false, "renal": false},
  "analysis_stale": false,
  "changed_summary": []
}
```

失败（保存失败等）返回 500 + `{error: "save_failed"}`，当前工作区原样保留。

### 5.3 GET `/profiles/{profile_id}/state`（恢复会话）

返回与 5.2 相同的结构（含最近 50 条消息、草稿、待确认动作、缺项、分系统状态、
`analysis_stale`、已确认资料摘要）。档案不存在返回 404。

### 5.4 POST `/profiles/{profile_id}/messages`（核心对话入口）

请求：

```json
{
  "op_id": "msg-2026-09-21-0001",
  "text": "上传的检查报告…",              // 粘贴文字或对追问的回答
  "file": {"name": "报告.pdf", "content": "<base64>"},   // 可选，同 smart-import
  "expected_version": 1                  // 可选；填写后服务端做版本并发检查
}
```

处理顺序：

1. 校验档案/会话归属与 `expected_version`（不匹配 → 409 `version_conflict`）。
2. 若存在 open 的待确认动作：先尝试把本条消息解析为该动作的答案（见 5.6），
   明确后执行；仍未明确继续追问；本条消息同时追加进会话消息列表。
3. 否则调用模型编排（AI-T05）：模型只允许提出白名单动作，服务端逐条校验后
   在同一数据库事务内执行，返回真实变更摘要。
4. 无模型/超时/忙时返回对应业务状态（见第 6 节），已保存内容不受影响。

响应 200：

```json
{
  "message_id": "m-0001",
  "reply": "已记录：2026-09-20 空腹血糖 5.8 mmol/L。还需要补充：吸烟状态未写。",
  "changed_summary": [{"action": "update_visit", "record_id": "v-1", "field": "fasting_glucose", "value": 5.8, "unit": "mmol/L"}],
  "pending_actions": [],
  "questions": ["吸烟状态？是/否/不知道"],
  "draft": {"sex": "male", "visits": [{"record_id": "v-1", "date": "2026-09-20", "fasting_glucose": 5.8}]},
  "draft_version": 3,
  "version": 1,
  "missing": ["visits.0.smoking", "visits.0.sbp"],
  "analysis_stale": false,
  "system_availability": {"cardiovascular": false, "glucose_metabolism": true, "renal": false},
  "service_state": "ready"
}
```

### 5.5 POST `/profiles/{profile_id}/confirm`（显式确认草稿）

请求：

```json
{"op_id": "op-confirm-1", "expected_version": 1}
```

服务端把草稿按 `PreventionRequest` 规则校验（必填项、日期、年龄一致、病史一致、
重复日期、越界），校验失败返回 422 + 缺项/错误列表，草稿原样保留，不写库。
成功：草稿转已确认资料，`version+1`，旧快照置 `stale`，生成新快照，返回完整变更摘要。
`expected_version` 不匹配 → 409 `version_conflict`。

### 5.6 追问回答的确定性解析

当存在 open 待追问问题时，后端按字段类型做确定性解析，解析失败才回退模型：

| 字段类型 | 解析规则 | 示例 |
| --- | --- | --- |
| 日期 | `YYYY-MM-DD` / `YYYY年M月D日` / “去年/前年/三年前”相对日期 | “去年”→ 依当前日期推算 |
| 数值+单位 | 数字 + 单位；单位与该记录不一致时按登记换算一次性换算（见 5.7） | “140 mmHg”、“5.8 mmol/L” |
| 布尔 | 是/否/有/无/吸/不吸/用/未用 | “吸烟” → true |
| 定性 | 正常/糖尿病前期/糖尿病/不知道 | “正常” → normal |
| “不知道” | 特殊标记 `unknown_explicit`，保存草稿并说明受限能力，不循环追问 | “不知道” |

回答“不知道”时：`changed_summary` 含 `unknown_explicit` 标记；`missing` 保留该字段，
但 `questions` 不再追问；`capabilities` 明确列出哪些能力无法计算。

### 5.7 单位纠正与单位换算分离

- 纠正单位标签：`update_visit {field: "chol_unit", value: "mg/dL"}` 只改标签，不改数值。
- 换算数值：新增/修改数值时给出不同单位 → 服务端按登记换算执行一次，且只执行一次
  （换算后的记录以目标单位存储，后续修改按该单位直接使用，不二次换算）。
- 有歧义时（如“改成 mg/dL”未指明是标签还是数值）先追问，不静默执行。
## 6. 错误码与业务状态

| HTTP | `error` | 含义 | 前端映射 |
| --- | --- | --- | --- |
| 400 | `invalid_input` | 请求格式/字段非法 | 导入区错误提示 |
| 404 | `not_found` | 档案/会话/快照不存在 | 返回列表 |
| 409 | `version_conflict` | 确认/操作基于过期版本 | “内容已被更新，请重新核对” |
| 409 | `duplicate_date` | 同日重复记录 | 解释并要求选择处理方式 |
| 422 | `validation_failed` | 草稿校验失败（附 `errors` 明细） | 展示缺项/冲突说明 |
| 422 | `invalid_model_output` | 模型输出非法/含未白名单动作 | “请重试” |
| 429 | `processing` | 单 worker 正在处理另一请求 | “正在处理中” |
| 503 | `model_unavailable` | 模型未就绪/离线 | “模型未就绪” |
| 504 | `timeout` | 模型处理超时 | “处理超时，请重试” |

重试规则：除 `validation_failed`/`version_conflict` 外，前端可直接携带相同 `op_id`
重试，服务端幂等返回第一次结果；`validation_failed` 需用户补充后重发新 op_id。
超时/取消/无效模型输出不会产生半完成写入（单事务提交）。

## 7. 幂等、版本与并发

- 所有写操作必须携带 `op_id`（UUID 字符串，客户端生成）。服务端以
  `(profile_id, op_id)` 去重：重复提交返回首次结果（200），不重复执行。
- 每次消息处理是单事务：模型动作全部通过校验才提交；任一条非法则整体回滚。
- 双页面同时修改或对过期草稿确认：携带 `expected_version` 的请求在版本不匹配时
  返回 409 `version_conflict`，前端提示重新核对并拉取 `state`，禁止覆盖新版本。
- 删除先明确对象再确认（open 待确认动作），采用软删除；撤销如遇后续修改返回冲突
  并解释，不覆盖新数据。
- 新建档案/切换时：旧请求即使稍后完成也只能作用于原档案并遵守确认与版本校验；
  迟到响应不得覆盖新工作区。

## 8. 前端调用顺序

### 8.1 主流程（上传 → 追问 → 回答 → 确认 → 点亮 → 规划 → 修改 → 重规划）

1. `GET /status` 检查模型就绪；未就绪显示导入区提示，不假装成功。
2. `POST messages`（上传文字/文件）→ 模型提取 → 返回 `draft`、`missing`、`questions`。
3. 存在 `questions` 时用户回复 → `POST messages`（回答）→ 重复直至 `pending_actions=[]`
   且 `missing` 仅剩“不知道”字段。
4. 用户表达确认（对话中或 `POST confirm`）→ 校验通过后 `version+1`，
   `system_availability` 变为可点亮集合。
5. `POST plan` 生成规划 → 快照 current；刷新后 `GET state` 恢复；`GET plans` 回看。
6. 修改/删除 → `POST messages` 或对话动作；确认后旧快照置 stale，`analysis_stale=true`
   提示重新规划；`POST plan` 基于新版本重生成。
7. 历史详情与整体规划从 `GET state` / `GET plans` 取数；建议原因简要、安排时间详细、
   依据来源简要；规则未给确定时间时 `due_date` 为 null（前端显示“未定”，模型不得编造）。

### 8.2 新建用户档案（AI-T08）

1. 用户点“＋ 新建档案” → 弹窗：“先保存当前规划？” 提供【先保存】【不保存继续】【取消】。
2. 【取消】→ 不发请求，页面原状态不变。
3. 【先保存】→ `POST plan`（当前档案），成功后再 `POST profiles {save_current:{save:"yes"}}`；
   保存失败提示留在当前档案，不切换。
4. 【不保存继续】→ 直接 `POST profiles {save_current:{save:"no"}}`；仅放弃未保存工作区，
   不删除旧档案已保存快照。
5. 新建成功：前端用返回的 `profile_id/session_id` 清空页面（人体 0/3、历史/规划空态、
   聊天上下文、附件、草稿、待确认动作、撤销上下文）；旧快照仍可从“已保存规划”只读回看
   （显示所属档案，只读回看不改变当前编辑对象）。

### 8.3 重新开始整理（与新建档案不同）

`POST restart`：清空本轮未确认文字/附件/草稿/待执行动作，对话上下文重新开始；
保留当前档案已确认资料与规划（`version`、快照不变）。用于同一人重新整理，不新建档案。

## 9. 分系统状态与点亮规则（0/3 人体）

`system_availability` 三系统：`cardiovascular`（心血管）、`glucose_metabolism`（血糖与代谢）、
`renal`（肾功能）。

- “有资料”= 该系统的已确认必需字段已具备；“可以计算”= 通过 `PreventionRequest` 校验
  且评估可执行（含年龄、日期新鲜度检查）。
- 点亮规则：`cardiovascular` 亮 = 已确认有 sbp/total_c/hdl_c/bmi 等心血管必需资料且校验通过；
  `glucose_metabolism` 亮 = 有 fasting_glucose/hba1c 或明确血糖状态；
  `renal` 亮 = 有 egfr 记录。
- 人体点亮代表“相关资料已确认”，不代表健康、疾病或风险结论。
- 详情页：`GET state` 返回 `confirmed_summary`（按系统分组）、`missing`、
  `capabilities`（如“无法计算：吸烟状态未知”）、`analysis_stale`（最新完整记录超 365 天）。
- 评估要求完整输入：不完整时返回可用资料 + 明确缺项，不补默认值强行计算。

## 10. 持久化与保留边界

- 数据库新增：`profiles`、`conversation_sessions`、`conversation_messages`、
  `profile_drafts`、`pending_actions`、`action_logs`、`archive_snapshots`（新表，不改旧表）。
- 原始文件/附件：仅内存处理（复用 smart-import 边界），不写入会话数据库。
- 快照保存 `assess()` 完整输出（输入/风险/建议/来源），与档案版本绑定，不冒充最新结果。
- 删除采用软删除 + 撤销日志；撤销链在新建档案时清空（撤销上下文不跨档案）。

## 11. 示例

### 11.1 成功闭环（上传 → 追问 → 回答 → 确认 → 规划）

```text
POST messages {op_id:"m1", text:"2026-09-20 体检：男，56岁，血压 138/85，总胆固醇 5.2 mmol/L，
HDL 1.3，BMI 26，eGFR 88，空腹血糖 5.8。无糖尿病、不吸烟、未用降压药和他汀。"}
→ 200 reply:"已提取待核对草稿。" questions:["请确认：吸烟状态是？(是/否/不知道)"]
   draft_version:1  missing:["visits.0.smoking"]  changed_summary:[…提取字段…]

POST messages {op_id:"m2", text:"不吸烟"}
→ 200 reply:"吸烟状态=否。必填项已齐，可确认或直接让我保存规划。"
   changed_summary:[{action:"update_visit", record_id:"v-1", field:"smoking", value:false}]
   missing:[] pending_actions:[] service_state:"ready"

POST confirm {op_id:"m3", expected_version:0}
→ 200 version:1 system_availability:{cardiovascular:true, glucose_metabolism:true, renal:true}
   changed_summary:[{action:"confirm", version:1}]

POST plan {op_id:"m4", expected_version:1}
→ 200 snapshot_id:"snap-1" snapshot_version:1 analysis_stale:false
   recommendations:[…规则建议…]
```

### 11.2 追问（缺项）

```text
POST messages {op_id:"m5", text:"收缩压 140，总胆固醇 5.2，BMI 26…（未写吸烟）"}
→ 200 questions:["吸烟状态？是/否/不知道"] pending_actions:[{id:"pa-1", field:"smoking",
   question:"吸烟状态？"}]
```

### 11.3 冲突（同日重复 / 版本冲突）

```text
POST messages {op_id:"m6", text:"2026-09-20 空腹血糖 6.0"}   // 同日已有记录
→ 409 duplicate_date {detail:"2026-09-20 已有记录，请选择：覆盖该记录、另存为新记录、放弃"}

POST confirm {op_id:"m7", expected_version:1}                // 实际版本已是 2
→ 409 version_conflict {detail:"档案已在其他页面被更新，请重新核对后再确认",
   current_version:2, expected_version:1}
```

### 11.4 取消 / 超时 / 模型离线

```text
POST messages {op_id:"m8", text:"删除昨天的记录"}   // 模型提 delete_visit，但未确认目标
→ 200 questions:["要删除哪一条？2026-09-19 血糖记录(v-2) / 2026-09-20 血压记录(v-1)"]
   pending_actions:[{id:"pa-2", action:"delete_visit", target:null}]

// 用户取消：
POST messages {op_id:"m9", text:"算了，不删了"} → pending_action pa-2 置 cancelled，无数据变化

// 超时：POST messages → 504 {error:"timeout"}；重试同 op_id → 幂等返回首次结果
// 模型离线：POST messages → 503 {error:"model_unavailable"}；GET state 仍可查看已保存内容
```

### 11.5 “不知道”

```text
POST messages {op_id:"m10", text:"吸烟状态？不知道"}
→ 200 reply:"已保存为‘不知道’。将无法计算 10/30 年风险中的吸烟项影响；
   其余已具备字段不受影响。可保存不完整草稿。"
   changed_summary:[{action:"unknown_explicit", field:"smoking"}]
   questions:[] capabilities:["可确认：血糖与代谢、肾功能；受限：心血管风险数值"]
```

### 11.6 单位纠正与换算

```text
// 纠正标签（不换算）：
POST messages {op_id:"m11", text:"单位写错了，是 mg/dL"}
→ 200 changed_summary:[{action:"update_visit", record_id:"v-1", field:"chol_unit",
   value:"mg/dL", converted:false}]

// 换算数值（一次性，不二次换算）：
POST messages {op_id:"m12", text:"总胆固醇 200 mg/dL"}
→ 200 changed_summary:[{action:"update_visit", record_id:"v-1", field:"total_c",
   value:5.18, unit:"mmol/L", converted:true, basis:"胆固醇换算 1 mmol/L=38.67 mg/dL"}]
```

## 12. 待与陈子正确认事项

1. 消息轮询方式：单请求-响应（模型较慢，建议前端按钮态 + 超时提示，不做流式）。
2. 新建档案弹窗文案与步骤（先保存/不保存继续/取消）的最终 UI 归属。
3. “人体点亮”三系统的字段映射是否与前端插画一一对应。
4. 快照只读回看的入口位置（历史详情页内 or 独立列表）。
5. 附件上传复用现有 smart-import 的文件处理边界，前端是否需要分片/压缩。

## 13. 已知限制

- 单 worker 串行处理（同 smart-import），忙时返回 429。
- 模型无工具调用能力，仅结构化动作提案；追问解析以确定性规则为主、模型兜底。
- 撤销仅支持最近一次数据修改/软删除；跨版本撤销返回冲突。
- 不训练模型、不改变 PREVENT 方程或现有医学规则含义；建议仍标记“待医学审核”。
<!-- CONTINUE -->


