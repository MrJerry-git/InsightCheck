# Medical Rule Engine

第七阶段规则引擎位于 `backend/app/rules/`，输入结构化受检者上下文、候选体检项目、DeepFM 分数、风险预测、检查史和病灶史，输出规则调整分数、最终状态、命中决定与完整执行轨迹。它不训练模型，也不作疾病诊断。

支持 `INTERVAL`、`DUPLICATE`、`RADIATION`、`AGE`、`GENDER`、`RISK`、`LESION_FOLLOWUP`、`MISSING_DATA` 八类规则，以及 `ALLOW`、`BOOST`、`REDUCE`、`DEFER`、`BLOCK`、`REVIEW_REQUIRED` 六类动作。

## 安全与确定性

- `BLOCK` 始终优先于其他动作，并将 `adjusted_score` 置为 `0`；DeepFM 高分不能绕过。
- 最终状态优先顺序为 `BLOCKED`、`REVIEW_REQUIRED`、`DEFERRED`、`ALLOWED`。
- 同类动作按 `priority` 降序，再按 `rule_code`、`version` 稳定排序。
- 配置无效的启用规则失败保护为 `REVIEW_REQUIRED`，不静默放行。
- 资料缺失由 `MISSING_DATA` 显式转为人工确认，不默认安全。
- 每次 API 请求都从数据库重新读取适用规则，并强制刷新 SQLAlchemy 已有实体，不使用规则缓存。

## 追溯

`RuleEvaluationResult` 保存 `deepfm_score`、`adjusted_score`、`final_status`、`rule_decisions`、`execution_trace`、`trace_id` 和基于规则代码、版本及启用状态生成的 `rule_set_version`。每条命中决定包含原因、来源、版本、优先级与证据引用。

`rule_violation_rate` 将已选中的 `BLOCKED`、`DEFERRED`，以及未经确认的 `REVIEW_REQUIRED` 项目计为违规；未选择项目不进入分母。

## API 与前端边界

- `POST /api/v1/rule-engine/evaluate`：Repository 读取规则，Service 编排，Rule Engine 独占裁决逻辑。
- `/recommendations/[id]`：仅展示后端结构化决定。当前页面样例明确标为 `DEMO DATA`，不执行任何医疗条件判断。
- 规则来源不能为空；API 校验与数据库约束同时保证。

本阶段没有录入真实临床规则。测试和页面中的规则均明确标注为演示/测试基线，不可作为临床指南。
