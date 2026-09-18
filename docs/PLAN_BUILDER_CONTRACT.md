# 方案构建服务接口契约（feat/plan-builder）

状态：**接口草案待负责人确认；其中两项口径已按建议定稿**（见文末「已定决策」）。
本文对应 [团队分工与分支任务书](TEAM_TASKS_V1.md) 中王天一的
「第一份交付：独立方案构建服务、输入输出约定和测试」，确认后再做 API 接入。

基线：`main` 的 53c210a。本次不修改 API 路由，不含医学规则与模型训练。

## 交付物

| 文件 | 作用 |
| --- | --- |
| `backend/app/services/plan_builder.py` | 三档方案构建服务（纯计算，无 IO）+ 快照转换 |
| `backend/app/services/pricing.py` | 费用与价格目录模型（整数分、来源、生效日期、演示价） |
| `backend/app/services/pricing_service.py` | 价格目录的数据库读写与演示价种子 |
| `backend/app/schemas/plan_builder.py` | 输入输出模型与枚举 |
| `backend/app/models/pricing.py` | `exam_item_prices` 持久化模型 |
| `backend/alembic/versions/b7e4c1a920d3_exam_item_prices.py` | 新增价格表迁移，编号 `b7e4c1a920d3` |
| `backend/tests/test_plan_builder.py`、`backend/tests/test_pricing_service.py` | 针对性测试 |

未修改 `api/routes/workflow.py`、`models/domain.py`、`schemas/domain.py`；
改动了 `models/__init__.py`（导出新模型）与 `tests/test_models.py`（表清单加一行）。

## 输入

`PlanBuildRequest`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trace_id` | str | 请求追踪号，写入快照 |
| `patient_id` | str | 受检者标识（不含身份信息） |
| `as_of_date` | date | 分析截止日期，决定取哪一版价格 |
| `candidates` | `PlanCandidate[]` | 候选项目及其**规则引擎已有结论** |
| `price_catalog` | `PriceCatalog` | 价格目录快照，可为空表示费用未知 |
| `budget` | `BudgetSpec \| null` | 预算偏好（金额整数分 + 币种） |
| `institution` / `region` | str \| null | 价格适用范围，用于优先取更具体价格 |
| `tiers` | `PlanTier[]` | 默认 `simplified/standard/deep` |
| `strategy_version` | str \| null | 覆盖默认策略版本，写入结果 |

`PlanCandidate`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `exam_item_id` / `code` / `name` / `category` | str | 项目标识与展示字段 |
| `radiation` | bool | 是否含辐射，档位策略依赖该字段 |
| `cost_level` | `CostLevel` | 复用现有 `low/medium/high`，用于档位策略 |
| `score` | float \| null | 现有排序分数（DeepFM 或规则调整后分数） |
| `rule_status` | `CandidateRuleStatus` | 规则结论：`ALLOWED/DEFERRED/BLOCKED/REVIEW_REQUIRED/NOT_CONFIGURED` |
| `rule_set_version` | str \| null | 规则集版本，汇总进结果 |
| `rule_notes` / `rule_evidence_refs` | str[] | 规则说明与证据引用 |

`CandidateRuleStatus` 提供两个适配入口，避免本服务重算规则：
`from_final_status(FinalRuleStatus)` 与 `from_rule_evaluation(RuleEvaluationResult)`
（后者在没有任何启用规则时返回 `NOT_CONFIGURED`，与 `workflow.py` 现有 `NOT_CONFIGURED`
判定一致，不视为审核通过）。

## 输出

`PlanBuildResult` → `tiers[]`（每个档位一份 `TierPlan`）

| 字段 | 说明 |
| --- | --- |
| `items[]` | 选入项目：`rank`、`score`、`rule_status`、`requires_review`、`selection_reason`、`cost_status`、`price`（快照） |
| `excluded[]` | 每个被排除项目一条：`reason_code` + 中文 `reason`，不静默丢弃 |
| `cost_summary` | 已知费用小计、已定价/未定价数量、未定价项目编码、是否完整、是否含演示价、按币种合计、披露文案 |
| `budget_status` | `within_budget / over_budget / unknown_prices / undetermined / not_provided` |
| `budget_note` | 预算结论的自然语言说明 |
| `conflicts[]` | 预算超额、未知价格、币种不一致、应复核项目超限、档位无差异等结构化冲突 |
| `identical_to[]` | 项目集合相同的其它档位 |
| `selection_note` | 本档策略、上限、可选候选数量与差异说明 |

结果级字段：`schema_version`、`strategy_version`、`rule_set_versions`、
`price_catalog_version`、`notes`、`disclosures`。

排除原因 `ExclusionReason`：`rule_blocked`、`rule_deferred`、`duplicate_candidate`、
`tier_item_limit`、`tier_radiation_policy`、`tier_cost_level_policy`、`budget_limit`。

## 三档策略（`strategy_version = plan-builder-v1`）

| 档位 | 项目数上限 | 含辐射项目 | 可选费用等级 | 说明 |
| --- | --- | --- | --- | --- |
| `simplified` | 4 | 否 | low / medium | 项目数最少，优先低费用 |
| `standard` | 8 | 否 | low / medium / high | 在基础档之上补充高费用项目 |
| `deep` | 16 | 是 | low / medium / high | 项目数最多，允许辐射项目 |

选取规则（确定性，与输入顺序无关）：

1. 按 `exam_item_id` 合并重复候选：**分数取最高，规则结论取最严格**
   （`BLOCKED` > `DEFERRED` > `REVIEW_REQUIRED` > `NOT_CONFIGURED`/`ALLOWED`），
   规则说明与证据引用取并集。模型分数或更高分记录不得覆盖禁止与暂缓结论；出现不同规则
   结论时写入 `duplicate_rule_status_conflict` 冲突，并在结果 `notes` 中说明。
2. 规则禁止项（`BLOCKED` / `DEFERRED`）在任何档位都不进入 `items`，即使分数最高或预算充足。
3. 规则要求复核项（`REVIEW_REQUIRED`）在所有档位优先保留，且不因预算或档位策略被删除；
   它们占用档位项目数，超出上限时产生 `review_items_exceed_tier_size` 冲突并保留全部。
4. 三档逐档生成：`standard` 以 `simplified` 的入选结果为起点扩充，`deep` 以 `standard`
   为起点扩充。`simplified ⊆ standard ⊆ deep` 因此恒成立，高档不会因预算或数量上限挤掉
   低档已选项目；承自低档的项目通过 `inherited_from` 标出来源档位。
5. 其余候选按 `(-score, code, exam_item_id)` 排序，逐项检查档位上限、辐射策略、
   费用等级策略与预算，命中则写入 `excluded` 并注明原因。
6. 若某档与其它档的项目集合相同，写入 `identical_to` 与 `tiers_not_distinct` 冲突并说明原因。

档位只表达项目组合与预算偏好，不表达疾病风险或医学必要性。

## 费用与预算语义

* 金额一律使用最小货币单位整数（分），全程无浮点累加；展示用 `format_amount` 整数拆分。
* 每条价格记录包含金额、币种、来源、可核验链接、适用机构或地区、生效与失效日期、
  是否演示价。`is_demo_price=False` 时强制要求 `source_url`，否则模型校验失败。
* 来源校验双重生效：`source` 与 `source_url` 去除首尾空白后不得为空，非演示价的链接必须是
  `http`/`https` 地址。模型层（`ExamItemPrice`）与数据库层（`exam_item_prices` 的
  `source_not_blank`、`source_url_not_blank`、`source_url_scheme` 约束）都会拒绝空白来源，
  不能用空格绕过来源要求。
* 价格按 `as_of_date` 生效区间取值，机构/地区更具体、生效更晚的优先。
* 预算筛选与最终汇总都按币种分别累计：只有与预算同币种的项目参与比较，其它币种从不与预算
  相加；存在无法换算的其它币种项目时返回 `undetermined`，文案明确写「总预算不可判定」。
* 已知费用小计只统计已定价项目；出现未知价格时 `is_complete=False`，
  `budget_status` 只能是 `unknown_prices`，文案明确写「不能据此声称总价完整或保证不超预算」。
* 规则要求与预算冲突时返回 `budget_exceeded` 冲突，应复核项目保留。
* 演示价必须标记 `is_demo_price=True`，并在 `cost_summary.disclosure` 中提示不能作为真实收费依据。

## 快照约定

`SelectedPlanItem.price` 是构建时冻结的价格副本（含 `catalog_version`、来源、生效日期）。
价格目录事后调整不会改变已生成的 `PlanBuildResult`；重新构建才使用新价。

`SelectedPlanItem` 同时保留输入中的规则依据：`rule_status`、`requires_review`、
`rule_set_version`、`rule_notes`、`rule_evidence_refs`，以及标记来源档位的 `inherited_from`。
保存后的方案因此仍能解释「为什么需要复核」，不需要回查当时的规则引擎输出。

`to_snapshot(result, adopted_tier=PlanTier.STANDARD)` 生成可直接写入 `AIReport.content`
的字典：

| 字段 | 说明 |
| --- | --- |
| `tiers` | 三档完整结果 |
| `tier_mode` | 固定 `single_request_all_tiers`，标记一次请求返回三档 |
| `adopted_tier` / `adopted_plan` | 实际采纳档位（默认 `standard`）及其同形结构，便于旧界面复用 |

接入 API 时把 `rule_set_versions` 摘要写入 `Recommendation.rule_version`，
`adopted_tier` 写入 `Recommendation.plan_tier`。

## 价格落库

新增表 `exam_item_prices`（迁移 `b7e4c1a920d3`，紧跟当前 head `d92a0175c310`）：

| 列 | 说明 |
| --- | --- |
| `exam_item_id` | 外键指向 `exam_items`，删除项目时级联删除价格 |
| `amount_cents` / `currency` | 整数分金额与三字母币种，均非空 |
| `source` / `source_url` | 来源说明与可核验链接 |
| `institution` / `region` | 适用范围，为空表示通用价格 |
| `effective_from` / `effective_to` | 生效区间，`effective_to` 可为空表示长期有效 |
| `is_demo_price` / `note` | 演示价标记与备注 |

数据库同样强制两条红线：`amount_cents >= 0`、生效区间有序，
以及非演示价必须有 `source_url`（`ck_exam_item_prices_real_price_requires_source_url`）。

`pricing_service.load_price_catalog(db, as_of_date=..., institution=..., region=...)`
按截止日期与适用范围读出行并生成 `PriceCatalog`，`catalog_version` 由价格内容哈希得出，
摘要覆盖金额、币种、来源与链接、适用机构与地区、生效与失效日期、演示价标记和备注，
任一影响查价或来源判断的字段变化都会换版本。`seed_demo_prices(db)` 为尚无价格的项目补
演示价，可重复执行。

## 接口示例（节选）

输入：3 个候选（`CHEST_CT` 被规则禁止、`THYROID_US` 得分 0.70、`LIVER_FUNCTION_PANEL`
得分 0.80），演示价格目录，预算 500.00 CNY。

```json
{
  "tier": "simplified",
  "strategy_version": "plan-builder-v1",
  "items": [
    {
      "code": "LIVER_FUNCTION_PANEL",
      "tier": "simplified",
      "rank": 1,
      "score": 0.8,
      "rule_status": "NOT_CONFIGURED",
      "requires_review": false,
      "selection_reason": "基础档：项目数最少，仅取低费用、无辐射项目：匹配分数 0.8000，费用 120.00 CNY（演示价）",
      "cost_status": "priced",
      "price": {
        "amount_cents": 12000,
        "currency": "CNY",
        "source": "DEMO PRICE：工程演示固定价格，不代表任何机构的真实收费",
        "is_demo_price": true,
        "catalog_version": "demo-price-catalog-v1"
      }
    }
  ],
  "excluded": [
    {"code": "CHEST_CT", "reason_code": "rule_blocked", "reason": "规则禁止：DEMO 规则：本轮禁止"},
    {"code": "THYROID_US", "reason_code": "budget_limit", "reason": "加入后已知费用将超过预算 500.00 CNY"}
  ],
  "cost_summary": {
    "currency": "CNY",
    "known_total_cents": 12000,
    "priced_item_count": 1,
    "unpriced_item_count": 0,
    "is_complete": true,
    "mixed_currency": false,
    "per_currency_totals": {"CNY": 12000},
    "includes_demo_price": true,
    "disclosure": "已知费用小计 120.00 CNY；包含演示价，仅用于工程演示，不能作为真实收费依据。"
  },
  "budget_status": "within_budget",
  "budget_note": "已知费用小计 120.00 CNY 在预算 500.00 CNY 之内。",
  "conflicts": [
    {"code": "tiers_not_distinct", "message": "本档与 standard、deep 档的项目集合相同：被档位策略或预算排除的项目与其它档位相同。"}
  ],
  "identical_to": ["standard", "deep"]
}
```

完整结果还包含 `standard`、`deep` 两份同结构对象，以及结果级的 `notes` 与 `disclosures`。

## 测试

```bash
cd backend
python -m pytest tests/test_plan_builder.py -q
python -m ruff check app/services/plan_builder.py app/services/pricing.py app/schemas/plan_builder.py
```

覆盖项与验收对应关系：

| 验收要求 | 用例 |
| --- | --- |
| 相同输入得到相同方案 | `test_same_input_same_output_and_order_independent` |
| 每档可解释、集合嵌套 | `test_tier_sets_are_nested_and_deep_allows_radiation` |
| 规则禁用项不因高分/预算恢复 | `test_blocked_item_never_returns_in_higher_tier`、`test_deferred_item_never_returns_in_higher_tier` |
| 预算不足不静默删除应复核项 | `test_review_items_survive_budget_conflict` |
| 应复核项超出档位上限 | `test_review_items_beyond_tier_limit_are_kept_and_reported` |
| 未知价格不声称总价完整 | `test_unknown_price_blocks_total_claim`、`test_budget_status_without_prices_or_budget` |
| 目录为空 / 无可选项目 | `test_empty_catalog_and_all_blocked_are_explained` |
| 重复候选 | `test_duplicate_candidates_are_deduplicated` |
| 价格更新后快照稳定 | `test_price_change_does_not_alter_saved_snapshot` |
| 多币种不合并 | `test_mixed_currency_is_not_summed` |
| 演示价标记 | `test_demo_prices_are_labelled_and_serializable` |
| 真实价格需可核验来源 | `test_real_price_requires_verifiable_source` |
| 价格生效区间与适用范围 | `test_lookup_prefers_specific_and_effective_price` |
| 档位无差异需说明原因 | `test_identical_tiers_are_reported_with_reason` |
| 复用规则引擎输出 | `test_plan_builder_can_consume_rule_engine_output` |
| 重复候选规则冲突按保守策略合并 | `test_duplicate_with_conflicting_rule_status_keeps_blocked`、`test_duplicate_deferred_beats_higher_score_allowed` |
| 重复候选合并保留全部规则证据 | `test_duplicate_merge_keeps_all_rule_evidence` |
| 跨币种预算不混算 | `test_cross_currency_budget_filter_does_not_mix_currencies` |
| 预算压力下三档仍嵌套 | `test_tiers_stay_nested_under_budget_pressure`、`test_inherited_items_record_origin_tier` |
| 入选项目保留规则依据 | `test_selected_items_keep_rule_evidence` |
| 来源非空白与链接格式（模型层） | `test_source_url_must_be_non_blank_http_address` |
| 来源非空白与链接格式（数据库层） | `test_database_rejects_blank_source_and_invalid_url` |
| 目录版本覆盖来源相关字段 | `test_catalog_version_covers_provenance_fields` |
| 演示价幂等落库 | `test_pricing_service.py::test_seed_demo_prices_is_idempotent` |
| 价格读取按截止日期与机构 | `test_load_price_catalog_respects_effective_range_and_institution` |
| 目录版本随价格变化 | `test_catalog_version_tracks_price_changes` |
| 真实价格必须有来源（数据库层） | `test_real_price_requires_source_url_in_database` |
| 数据库价格驱动三档与快照 | `test_plan_builder_consumes_database_price_catalog` |

## 已定决策

1. **一次请求返回三档**（`tier_mode = single_request_all_tiers`），不拆成三次请求。
  理由：三档必须基于同一份价格目录和同一次输入截断，拆开容易出现档位间口径漂移；
  前端一次请求即可出对比；模型与规则只跑一次。
  `Recommendation.plan_tier` 记录用户实际采纳的档位（默认 `standard`）。

   `tier` 目前**仍然参与请求冲突判定**（同一 `request_id` 改 `tier` 视为不同输入，
   `tests/test_workflow.py` 的既有断言保持不变），本次不动，等整合接口时再统一确定。
2. **价格落库。** 新增 `exam_item_prices` 表与迁移 `b7e4c1a920d3`，演示价由
   `seed_demo_prices` 幂等写入；接口层用 `load_price_catalog` 取当期价格。
  理由：`institution`/`region`/生效区间只有在持久化后才有一致来源，避免 JSON 与
   `exam_items` 两套事实。

   服务输出（`PlanBuildResult` / `to_snapshot`）是新的数据结构，**不能直接当作旧页面已经
   兼容**：本次只保证服务输出与证据保存完整，实际 API 接入、保存回读与旧页面适配由负责人
   协调，前端由陈子正接。

## 仍需负责人确认

1. **`plans/{id}/explain` 的费用分支文案**（当前写死「尚未接入真实价格，当前无法计算总费用」）
   是否改为读取 `cost_summary` 与 `budget_note`。
2. **`Recommendation.rule_version`** 是否填 `rule_set_versions` 的摘要值。
3. **前端接入细节**：三档命名、字段命名与展示顺序需与陈子正确认；新增三档界面待本契约确认后接入。
