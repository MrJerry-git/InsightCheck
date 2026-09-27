# H08 真实语言模型接入运行记录

任务：H08 结构化解释与真实语言模型问答服务
负责人：王宏锦（WHJ-2007）
记录文件：`docs/llm-qa-run-record.json`（由 `backend/scripts/llm_qa_smoke.py` 生成）

## 为什么要有这份记录

PR #26 审查指出：**模拟 provider 与模板测试不等同于模型接入**。本记录是一次真实
模型调用的产物，走的是项目自身的 `OpenAICompatibleLLMProvider` + `QAService`，
不是测试替身。

## 接入方式

| 项 | 值 |
| --- | --- |
| 适配器 | `app.llm.openai_compat.OpenAICompatibleLLMProvider` |
| 协议 | OpenAI 兼容 `/chat/completions`（HTTPS 强制） |
| 接入点 | 环境变量 `IC_LLM_BASE_URL` / `IC_LLM_API_KEY` / `IC_LLM_MODEL` |
| 本次模型 | `deepseek-chat` |
| 依赖 | 仅标准库 `urllib`，未新增运行依赖 |

密钥只从环境变量读取，不落盘、不进 Git、不进前端。未配置凭据时
`is_available()` 为 `False`，脚本写出 `status: skipped` 并说明原因，
**不伪造调用记录**。

## 运行方式

```bash
cd backend
IC_LLM_BASE_URL="https://api.deepseek.com/v1" \
IC_LLM_API_KEY="<key>" \
IC_LLM_MODEL="deepseek-chat" \
python scripts/llm_qa_smoke.py
```

## 本次结果

证据输入三条，**编号故意与输入顺序不一致**（EV-9 / EV-2 / EV-5），
用来验证「编号—正文」绑定没有按编号排序错位：

| 编号 | 正文 | 来源记录 |
| --- | --- | --- |
| EV-9 | 空腹血糖 7.2 mmol/L（偏高） | rec-labs-2026-06-01 |
| EV-2 | 尿酸 480 μmol/L（偏高） | rec-labs-2026-06-01 |
| EV-5 | 体质指数 27.4 kg/m2（超重） | rec-body-2026-06-01 |

模型回答（原文见 JSON，未删改）：

```
本次体检中，依据所给证据，需要复查的异常有以下 3 条：

1. 空腹血糖 7.2 mmol/L（偏高）[EV:EV-9]
2. 尿酸 480 μmol/L（偏高）[EV:EV-2]
3. 体质指数 27.4 kg/m2（超重）[EV:EV-5]
```

| 指标 | 结果 |
| --- | --- |
| 运行状态 | ok |
| 模式标注 | `model`（非模板） |
| 模型标识 | `deepseek-chat` |
| 耗时 | 1.408 s |
| 引用提回 | EV-9 / EV-2 / EV-5，全部命中真实编号 |
| 无效引用移除 | 无 |
| 编号→来源记录解析 | 三条全部解析到 `rec-*`，绑定正确 |

对照：同一上下文在 `local-template` 模式下产出确定性模板文本，
`llm_model=local-template`、`mode=template`，两者在响应中明确区分，不冒充。

## 引用绑定与守卫（PR #26 P1）

修复前：`qa.py` 只把 `normalized_findings` 的文本列表发给模型，
`evidence_refs` 单独按编号排序，`record_ref` 丢失。两处顺序不一致时模型
无法判断哪段文字对应哪个 `[EV:...]`，守卫也**只检查编号存在性**，
会接受「引用到错误记录」的回答。

修复后：

1. `StructuredPatientContext` 新增 `evidence_items: list[EvidenceItem]`，
   强制 **(ref_id, text, record_ref) 三元组**绑定，并随上下文一起下发；
   `format_evidence_block()` 输出成对清单，编号紧跟对应正文与来源记录。
2. `evidence_pairs()` 保持传入顺序，**不再按编号排序**。
3. `QAService._finalize` 增加第二道守卫 `_mismatched_citations`：
   编号存在但句中文字属于另一条证据 → 判定引用错记录，同样摘除并加注
   「与所引编号不匹配」。
4. `QAAnswer.citation_records` 输出 `(ref_id, record_ref)` 对，引用可回溯到来源记录。

## 已知局限

- 错配判定基于「数值+单位」特征片段的保守规则，只标注明确可判定的错配；
  纯语义层面的张冠李戴仍需人工核对兜底，不宣称自动判定全部错配。
- 本次记录是一次真实调用样本，用于证明接入可用；不构成质量评测，
  批量评测与安全红线检查另见 H08/H10 规划。
- 接入点凭据由部署环境提供，仓库内不含任何密钥。
