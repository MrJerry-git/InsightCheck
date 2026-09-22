# 可复用模型/组件清单与接入状态（H10）

负责人：王宏锦（WHJ-2007）。角色：本文件登记**实际接入的组件与真实运行记录**，不代为验收他人任务。原则：**OCR/抽取/问答优先接入**；检查权重版本、许可、预处理、资源与运行证据后才登记"已接入"；不为等待风险模型拖延其余功能（TEAM_TASKS_V2.md 第六节）。

"接入状态"取值：

- `integrated`：已在本仓库代码路径中实际运行，**且本文件或链接文档给出运行记录**；
- `written`：代码已写好但**未在真实引擎/凭据下跑通过**（等待安装或凭据，不冒充已接入）；
- `evaluated`：完成选型评估，尚未写适配器；
- `not_started`：仅记录候选。

> 状态口径说明：本清单以 **main 的真实状态**为准。某一分支上的适配器代码即使已提交，
> 只要还没在真实引擎/凭据下运行过，一律记 `written`，并注明其所在 PR；
> 只有 `integrated` 才是"可验收"的接入。相关 PR 尚有阻断问题时不予升格。

---

## 零、既有参赛能力与新增 H 模块的边界（先读）

本仓库同时存在**两批代码**，边界必须分清，否则会误判能力范围：

| 批次 | 来源 | 落点 | 说明 |
| --- | --- | --- | --- |
| **参赛版既有能力** | 1.0 版本已在 main 合入、参加比赛时已有 | `app/services/prevention.py`、`app/services/smart_import.py`、`app/ml/recommendation/`、`app/services/plan_builder.py` | 含 PREVENT 心血管风险计算、本地 Qwen 智能导入、DeepFM 排序。**这些是已存在的能力**，不是本轮新做 |
| **本轮新增 H 模块** | TEAM_TASKS_V2.md 第六节分工，分支开发中 | `app/tabular_parsing/`、`app/report_extraction/`、`app/cross_system/`、`app/features/lesion/`、`app/rule_candidates/`、`app/llm/` | 表格解析、报告抽取、跨系统分析、影像病灶、规则候选、问答服务 |

**风险提示（避免混淆）**：下文的"本轮不接入风险模型"指的是 **H09 任务注册表里
`awaiting_data` 的 LightGBM 疾病风险模型**（需 NLST 训练数据）。这与参赛版
**已有的 PREVENT 计算**是两码事——PREVENT 是**公开方程的实现**，已在 main 运行，
本轮不打折、不替换、不降级。

---

## 一、文件与表格解析

| 组件 | 用途 | 许可 | 接入状态 | 落点与证据 |
| --- | --- | --- | --- | --- |
| Python `csv`（标准库） | CSV 行读取 | PSF | `integrated`（main 既有） | 导入链路；编码探测归文件管理，解析吃已解出行 |
| openpyxl 3.1 | Excel(.xlsx) 只读值 | MIT | `written`（PR #19 `feat/tabular-parsing`） | `app/tabular_parsing/excel.py`；测试含真实 xlsx 生成与读取。待 #19 合入 main 后升格 |
| pypdf 5.x / 6.x | PDF 文本层抽取 | BSD-3 | `written`（PR #20 `feat/report-extraction`） | `app/report_extraction/text_source.py`；测试含自制最小 PDF 夹具（页码/行号验证）。待 #20 合入后升格 |
| pypdfium2 | PDF 逐页栅格化 | BSD-3 / Apache-2.0 | `integrated`（main 既有） | `app/services/smart_import.py`：既有智能导入用它对 PDF 逐页转图喂本地多模态模型 |

已知限制：pypdf 对嵌入 CID 字体的中文 PDF 依赖字体 ToUnicode 映射；机构版式中文 PDF 需用真实样例验证（数据到达后在"本机构报告适配"任务中处理）。

---

## 二、OCR 与影像文字

| 组件 | 用途 | 许可 | 接入状态 | 说明 |
| --- | --- | --- | --- | --- |
| RapidOCR（`rapidocr-onnxruntime`） | 图片/扫描件 OCR | 代码 Apache-2.0；**模型权重随包分发，另适用其自身许可** | `integrated`（PR #20 `feat/report-extraction`） | `app/report_extraction/ocr.py` RapidOcrAdapter：延迟导入，未安装时 `is_available()=False` 并给出安装说明。**真实运行记录见第四节** |
| PyMuPDF（`fitz`） | PDF 页栅格化（供 OCR 前处理） | **AGPL-3.0 或商业许可**（非宽松许可，需注意） | `integrated`（PR #20） | `app/report_extraction/render.py` PyMuPdfRenderer，dpi=200。**许可须在部署前按使用方式确认**（见第五节） |
| PaddleOCR | 备选 OCR | Apache-2.0 | `evaluated` | 模型与依赖较重（PaddlePaddle 运行时）；RapidOCR 满足需求时不引入 |
| Tesseract（pytesseract） | 备选 OCR | 代码 Apache-2.0；语言包另计 | `evaluated` | 需系统级二进制安装，Windows 部署成本高；中文需额外语言包 |

---

## 三、语言模型（问答/解释）

| 组件 | 用途 | 许可 / 边界 | 接入状态 | 落点与证据 |
| --- | --- | --- | --- | --- |
| `local-template` | 确定性结构化解释 | 本项目代码 | `written`（PR #26 `feat/llm-qa-service`） | `app/llm/templated.py`；显式标注 `llm_model=local-template`，不冒充模型输出 |
| OpenAI 兼容聊天接口 | 真实模型问答 | 供应商条款；密钥只从环境变量读，不进 Git | `written`（PR #26） | `app/llm/openai_compat.py`；强制 HTTPS、显式错误不降级为编造内容；引用守卫在 `app/llm/citations.py`。**真实调用记录见第四节** |
| 本地 Qwen 智能导入（Ollama） | 体检资料 OCR/抽取成结构化字段并由证据门控 | Ollama 服务条款 + **所下载权重的模型许可**（见第五节） | `integrated`（main 既有，参赛版功能） | `app/services/smart_import.py`；配置 `import_model_url`（强制本机 HTTP）+ `import_model`（默认 `qwen3-vl:4b-instruct`）+ `import_model_timeout=240` |
| DeepFM（本项目自实现） | Patient×ExamItem 匹配排序 | 项目内代码 | `integrated`（main 既有，**合成演示**） | `app/ml/recommendation/`；仅合成演示运行，真实制品接入见 H09 注册表 |

---

## 四、已选择的模型：权重版本、许可、预处理、资源与运行记录

### 4.1 组件许可 vs 权重许可（必须分开记录）

审查明确指出：**仓库代码许可不等于权重许可**。逐项分开登记：

| 组件 | 代码许可 | 权重/数据许可 | 归属与要求 |
| --- | --- | --- | --- |
| RapidOCR（rapidocr-onnxruntime） | Apache-2.0 | 随包分发的 ONNX 权重**适用其各自上游许可**（PaddleOCR 系列权重） | 需在部署清单中固定包版本，并保留上游许可文本 |
| PyMuPDF | **AGPL-3.0**（或购买商业许可） | 无（无权重） | **AGPL 具有传染性**：以网络服务形式提供须评估开源义务，或改用商业许可/替代库 |
| Ollama + Qwen 权重 | Ollama MIT | Qwen 权重按**其发布方许可**（如 Apache-2.0 / Qwen 许可，具体以所选权重卡为准） | 须记录**下载来源 + 权重卡许可 + 校验值**，不因为 Ollama 是 MIT 就当作权重也 MIT |
| PREVENT 系数 | `preventr` 0.12.0（MIT） | 系数为公开发表值 | 见 4.2 |

### 4.2 PREVENT 心血管风险（main 既有）

| 项 | 记录 |
| --- | --- |
| 实现 | `app/services/prevent_equations.py`，`MODEL_VERSION = preventr-0.12.0-python-1` |
| 上游 | `preventr` 0.12.0 的 `prep_terms` / `run_models` 的 Python 移植（MIT） |
| 系数 | `app/services/prevent_coefficients.json`，**未修改** |
| 暴露范围 | 仅 base / HbA1c 两个变体 + 三个主要结局（total_cvd / ascvd / heart_failure）；10 年与 ≤59 岁的 30 年 |
| 预处理 | 胆固醇单位换算（mg/dL ↔ mmol/L，0.02586）；non-HDL、BMI 与 SBP 的截断项、年龄交互项按原文计算 |
| 适用性门控 | `eligibility()` 逐项校验年龄 30–79、SBP 90–200、TC 130–320 mg/dL、HDL 20–100 mg/dL、BMI 18.5–39.9、eGFR 15–140、HbA1c 4.5–15；**超范围直接抛错，不外推** |
| 运行记录 | **真实公开数据冒烟已留存**：`docs/NHANES_PREVENT_AUDIT.json` — CDC NHANES 2017–2018 公开数据，拼接 2966 条无处方记录，229 条完整且模型内，59 条因超出模型范围排除；各源表 URL 与 sha256 齐全。**声明：这是计算冒烟验证，不是准确率实验** |
| 资源 | 纯 CPU 计算，无外部服务；系数文件约 12 KB |

### 4.3 本地 Qwen 智能导入（main 既有）

| 项 | 记录 |
| --- | --- |
| 实现 | `app/services/smart_import.py` |
| 运行时 | 本机 Ollama HTTP（`import_model_url`，仅允许 localhost/127.0.0.1/::1，非本机地址直接被校验器拒绝） |
| 权重 | `import_model` 默认 `qwen3-vl:4b-instruct`；**该值可在 `.env` 覆盖，因此以实际部署值 + 权重卡许可为准记录** |
| 预处理 | 图片：`PIL` 打开并防解压炸弹（>2000 万像素拒绝）→ 转 RGB → 缩到 1800px 内 → JPEG q90；`.docx`：解 `word/document.xml`，正文 >2 MB 拒绝，禁 DTD/实体（防 XXE）；`.pdf`：pypdfium2 逐页，限 1–5 页 |
| 输入上限 | 文件 1 字节–8 MB；PDF ≤5 页 |
| 反幻觉约束 | 提示词要求逐字抄录 `{path, quote}` 证据；**不得计算/推断原文没有的年龄、日期、病史**；不能据数值诊断血糖状态 |
| 资源 | 4B 级多模态模型，需本机可承载 Ollama 推理（显存/内存取决于量化方式，部署时按实际机器记录） |
| 运行记录 | **待补**：需在本机 Ollama 下用真实样例（如机构体检资料）跑通并留存输入、输出与人工比对结论；当前仓库内**未见该运行记录文件**，因此不在本清单宣称已完成的端到端验收 |

### 4.4 真实模型问答（PR #26 `feat/llm-qa-service`）

| 项 | 记录 |
| --- | --- |
| 适配器 | `app/llm/openai_compat.OpenAICompatibleLLMProvider`（仅标准库 urllib，无新增依赖） |
| 本次模型 | `deepseek-chat`（OpenAI 兼容 `/chat/completions`，强制 HTTPS） |
| 运行记录 | **`docs/llm-qa-run-record.json`**（由 `backend/scripts/llm_qa_smoke.py` 生成）+ 说明文档 `docs/LLM_QA_RUN.md` |
| 实测结果 | mode=`model`，耗时 **1.408 s**；证据编号故意与输入顺序不一致（EV-9/EV-2/EV-5），模型三条引用全部命中且编号→来源记录解析正确，无无效引用 |
| 反幻觉约束 | 编号与正文**成对**下发；除"编号必须存在"外，另校验"引用与所引内容不得错位"，错配同样摘除并加注 |

### 4.5 OCR 真实运行记录（PR #20 `feat/report-extraction`）

| 项 | 记录 |
| --- | --- |
| 环境 | Python 3.12.10 / pymupdf 1.27.2.3 / rapidocr-onnxruntime 1.4.4 / pypdf 6.19.0 |
| 记录文件 | `docs/ocr-run-record.json` + 说明 `docs/REPORT_EXTRACTION_OCR_RUN.md` |
| 结果 | `scan_2p` **ok** 2.314 s（2 页全扫描）；`mixed` **ok** 0.688 s；`multi_3p` **partial** 1.365 s（第 3 页 `ocr_empty_result`，显式登记失败页，不整体报成功） |
| 预处理 | PyMuPDF 200 dpi 栅格化后交 RapidOCR；逐页登记 `text_layer` / `ocr` / `failed` |
| 已知限制 | 空白页会得 `ocr_empty_result`，按 `partial` 返回并列出失败页，不冒充全文成功 |

---

## 五、部署前必须确认的许可问题

1. **PyMuPDF 为 AGPL-3.0**。以网络服务形式对外提供时，AGPL 的开源义务需要评估；
   如需闭源或避免传染，应改用商业许可或替换栅格化方案（如 pypdfium2，main 既有智能
   导入已在用）。**当前 #20 的 PDF 栅格化用了 PyMuPDF，合入前需给出结论。**
2. **RapidOCR / Qwen 的权重许可单独记录**，不随代码许可；部署清单须固定包与权重版本。
3. 密钥一律环境变量注入，仓库内不得出现任何凭据（已按此实现）。

---

## 六、明确不在本轮接入

- 原始 CT/MRI 图像的自动检出、分割与诊断模型（任务书明确排除）；
- **H09 任务注册表中 `awaiting_data` 的 LightGBM 疾病风险模型**（需 NLST 训练数据；
  在此之前不产出疾病概率）。

> 边界澄清：上一条**不涉及**参赛版已有的 PREVENT 计算（见 4.2）。PREVENT 是公开发表
> 方程的确定性实现，已在 main 运行并有真实公开数据冒烟记录，本轮不替换、不降级。

---

## 七、新增组件的登记要求

任何新组件接入前必须记录：用途、**代码许可与权重许可（分开）**、权重版本与来源、
资源需求、预处理要求、运行证据（测试或真实样例记录）、回退与显式不可用行为。
缺任何一项不得标 `integrated`。
