# 可复用模型/组件清单与接入状态（H10）

负责人：王宏锦（WHJ-2007）。角色：本文件登记**实际接入的组件、权重与运行证据**，不代为验收他人任务。原则：**OCR/抽取/问答优先接入**；检查权重版本、许可、预处理、资源与运行证据后才登记；不为等待风险模型拖延其余功能（TEAM_TASKS_V2.md 第六节）。

## 状态口径（两条独立轴，避免互相矛盾）

**A. 接入状态（代码路径是否进入 main）**

- `integrated`：组件已合入 **main**，位于真实调用路径中，可在干净检出运行；
- `written`：代码已写好但**在未合并分支上**（注明 PR），未进入 main；
- `evaluated`：完成选型评估，尚未写适配器；
- `not_started`：仅记录候选。

**B. 运行验证（本次部署选型是否真实跑通并留存证据）**

- `verified`：有可复现的真实运行记录（给出文件路径）；
- `pending`：**尚未**在真实引擎/数据/凭据下跑通；**不得**因代码路径已 integrated 就当作已验证；
- `n/a`：无权重、无外部运行面（纯计算、合成演示）。

> 关键区分：`integrated` 只说明"main 里有这条代码路径"，**不**等于"本次部署已用真实权重/数据验证过"。
> 两者必须分别标注——这正是上一版把 Qwen 标成 integrated 却写"运行记录待补"的矛盾所在。
> main 当前已合入 H01/H02/H03/H06/H07/H08/H09/H11；**H04（#20）、H05（#21）仍在未合并分支**，
> H10/H12 为本文件与联调套件。相关 PR 尚有阻断问题时不予升格（见第七节）。

---

## 零、既有参赛能力与新增 H 模块的边界（先读）

| 批次 | 来源 | 落点 | 说明 |
| --- | --- | --- | --- |
| **参赛版既有能力** | 1.0 已在 main 合入、参赛时已有 | `app/services/prevention.py`、`app/services/prevent_equations.py`、`app/services/smart_import.py`、`app/ml/recommendation/`、`app/services/plan_builder.py` | 含 PREVENT 心血管风险计算、本地 Qwen 智能导入、DeepFM 排序。**这些是已存在的能力**，不是本轮新做 |
| **本轮新增 H 模块** | TEAM_TASKS_V2.md 第六节分工 | 已合入：`app/exam_dictionary/`(H01/H02)、`app/tabular_parsing/`(H03)、`app/features/lesion/`(H06)、`app/rule_candidates/`(H07)、`app/llm/`(H08)、`app/ml/tasks/`(H09)、`app/jiuhua_prep/`(H11)；**未合入**：`app/report_extraction/`(H04,#20)、`app/cross_system/`(H05,#21) | 表格解析、报告抽取、跨系统分析、影像病灶、规则候选、问答服务 |

**风险提示（避免混淆）**：下文的"本轮不接入风险模型"指的是 **H09 任务注册表里
`awaiting_data` 的 LightGBM 疾病风险模型**（需 NLST 训练数据）。这与参赛版
**已有的 PREVENT 计算**是两码事——PREVENT 是**公开方程的实现**，已在 main 运行，
本轮不打折、不替换、不降级。

---

## 一、文件与表格解析

| 组件 | 用途 | 代码许可 | 接入状态 | 运行验证 | 落点与证据 |
| --- | --- | --- | --- | --- | --- |
| Python `csv`（标准库） | CSV 行读取 | PSF | `integrated`（main 既有） | `n/a` | 导入链路；编码探测归文件管理，解析吃已解出行 |
| openpyxl 3.1.5 | Excel(.xlsx) 只读值 | MIT | `integrated`（#19 已合入 main） | `verified` | `app/tabular_parsing/excel.py`；`tests/tabular_parsing` 含真实 xlsx 生成与读取 |
| pypdf 6.19.0 | PDF 文本层抽取 | BSD-3-Clause | `written`（PR #20 `feat/report-extraction`） | `verified`（PR #20 分支） | `app/report_extraction/text_source.py`；自制最小 PDF 夹具验证页码/行号 |
| pypdfium2 5.13.0 | PDF 逐页栅格化 | BSD-3-Clause / Apache-2.0 | `integrated`（main 既有） | `verified`（PR #20 分支） | `app/services/smart_import.py` 既有；#20 `render.py` 亦以其为**默认**渲染后端 |

已知限制：pypdf 对嵌入 CID 字体的中文 PDF 依赖字体 ToUnicode 映射；机构版式中文 PDF 需用真实样例验证（数据到达后在"本机构报告适配"任务中处理）。

---

## 二、OCR 与影像文字

| 组件 | 用途 | 代码许可 | 接入状态 | 运行验证 | 说明 |
| --- | --- | --- | --- | --- | --- |
| RapidOCR（`rapidocr-onnxruntime` 1.4.4） | 图片/扫描件 OCR | Apache-2.0（权重清单见 4.1） | `written`（PR #20，未合并） | `verified`（PR #20 分支） | `app/report_extraction/ocr.py` RapidOcrAdapter：延迟导入，未安装时 `is_available()=False` 并给出安装说明。**运行记录见 4.5** |
| onnxruntime 1.28.0 | RapidOCR 推理运行时 | MIT | `written`（PR #20，未合并） | `verified`（PR #20 分支） | 随 RapidOCR 引入；权重为预训练 ONNX，见 4.1 |
| pypdfium2 5.13.0 | PDF 页栅格化（OCR 前处理） | BSD-3-Clause / Apache-2.0 | `written`（PR #20，未合并） | `verified`（PR #20 分支） | `app/report_extraction/render.py` **默认** `Pypdfium2Renderer`，dpi=200 |
| PyMuPDF（`fitz`） | PDF 栅格化**可选回退** | **AGPL-3.0 或商业许可** | `written`（PR #20，未合并） | `pending`（非默认路径，未纳入验收） | 仅在未安装 pypdfium2 时回退；**不再是默认方案**，见第五节 |
| PaddleOCR | 备选 OCR | Apache-2.0 | `evaluated` | `not_started` | 模型与依赖较重（PaddlePaddle 运行时）；RapidOCR 满足需求时不引入 |
| Tesseract（pytesseract） | 备选 OCR | 代码 Apache-2.0；语言包另计 | `evaluated` | `not_started` | 需系统级二进制安装，Windows 部署成本高；中文需额外语言包 |

---

## 三、语言模型（问答/解释）

| 组件 | 用途 | 许可 / 边界 | 接入状态 | 运行验证 | 落点与证据 |
| --- | --- | --- | --- | --- | --- |
| `local-template` | 确定性结构化解释 | 本项目代码 | `integrated`（#26 已合入 main） | `n/a`（确定性） | `app/llm/templated.py`；显式标注 `llm_model=local-template`，不冒充模型输出 |
| OpenAI 兼容聊天接口 | 真实模型问答 | 供应商条款；密钥只从环境变量读，不进 Git | `integrated`（#26 已合入 main） | `verified` | `app/llm/openai_compat.py`；强制 HTTPS、显式错误不降级为编造内容；引用守卫在 `app/llm/citations.py`。**记录见 4.4** |
| 本地 Qwen 智能导入（Ollama） | 体检资料 OCR/抽取成结构化字段并由证据门控 | Ollama MIT + **所下载权重的模型许可** | `integrated`（main 既有代码路径，参赛版功能） | **`pending`** | `app/services/smart_import.py`；配置 `import_model_url`（强制本机 HTTP）+ `import_model`（默认 `qwen3-vl:4b-instruct`）+ `import_model_timeout=240`。**权重与运行验证待部署时按 4.1/4.3 补齐** |
| DeepFM（本项目自实现） | Patient×ExamItem 匹配排序 | 项目内代码 | `integrated`（main 既有，**合成演示**） | `n/a`（合成数据） | `app/ml/recommendation/`；仅合成演示运行，真实制品接入见 H09 注册表 |

---

## 四、部署清单：版本、来源、许可、校验值、运行记录

### 4.1 本次部署组件与权重清单（实际选型；未跑通的标 pending）

**代码许可 ≠ 权重许可**。逐项分开登记，权重按**不可变版本 + 校验值**固定。

| 组件 | 不可变版本 | 权重/制品文件 | 校验值（sha256） | 下载来源 + 许可 | 运行验证 |
| --- | --- | --- | --- | --- | --- |
| rapidocr-onnxruntime | 1.4.4 | `ch_PP-OCRv4_det_infer.onnx`（4,745,517 B） | `d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9` | PyPI；上游 <https://github.com/RapidAI/RapidOCR>；包许可 Apache-2.0 | `verified` |
| ↑ 同上 | ↑ | `ch_PP-OCRv4_rec_infer.onnx`（10,857,958 B） | `48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b` | 权重源自 PaddleOCR 系列（Apache-2.0），随包分发 | `verified` |
| ↑ 同上 | ↑ | `ch_ppocr_mobile_v2.0_cls_infer.onnx`（585,532 B） | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` | 同上 | `verified` |
| onnxruntime | 1.28.0 | 无独立权重（ONNX 运行时） | 包哈希由 PyPI 提供 | PyPI；MIT | `verified` |
| pypdfium2 | 5.13.0 | 随包绑定的 **PDFium 153.0.7999.0**（来自 pdfium-binaries） | 包内 `LICENSES/` 与 `data/windows_x64/BUILD_LICENSES/` 已含逐依赖许可文本 | PyPI；BSD-3-Clause / Apache-2.0；PDFium 及各依赖许可随包 | `verified` |
| pypdf | 6.19.0 | 纯 Python，无权重 | 包哈希由 PyPI 提供 | PyPI；BSD-3-Clause | `verified` |
| openpyxl | 3.1.5 | 纯 Python，无权重 | 包哈希由 PyPI 提供 | PyPI；MIT | `verified` |
| Pillow | 12.3.0 | 无权重（图像 I/O 与预处理） | 包哈希由 PyPI 提供 | PyPI；MIT-CMU | `verified` |
| Ollama + Qwen 权重 | **待定** | `qwen3-vl:4b-instruct`（**默认 tag，可被 `.env` 覆盖**） | **待补**（部署后用 `ollama show --modelfile`/registry digest 记录不可变 digest） | 下载来源：Ollama 模型库；权重许可**以所选权重卡为准**（不因 Ollama MIT 就当作权重 MIT） | **`pending`** |
| DeepSeek Chat | API（`deepseek-chat`） | 无本地权重 | `n/a` | 供应商 API + 服务条款 | `verified`（#26） |

> 说明：上表未跑通的项只有在**真实性前提下**才标 `verified`——例如 Qwen 权重未在本机
> Ollama 下跑通，就明确标 `pending`，不因 `smart_import.py` 已合入 main 而默认通过。

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

### 4.3 本地 Qwen 智能导入（main 既有代码路径；运行验证 pending）

| 项 | 记录 |
| --- | --- |
| 实现 | `app/services/smart_import.py` |
| 运行时 | 本机 Ollama HTTP（`import_model_url`，仅允许 localhost/127.0.0.1/::1，非本机地址直接被校验器拒绝） |
| 权重 | `import_model` 默认 `qwen3-vl:4b-instruct`；**该值可在 `.env` 覆盖**，因此以实际部署值 + 权重卡许可为准记录 |
| 权重清单 | **待补（pending）**：需记录①实际部署的**不可变 digest**（而非可漂移的 tag）；②下载来源与权重卡链接；③权重卡许可文本副本与 SHA-256；④量化方式与文件校验值 |
| 预处理 | 图片：`PIL` 打开并防解压炸弹（>2000 万像素拒绝）→ 转 RGB → 缩到 1800px 内 → JPEG q90；`.docx`：解 `word/document.xml`，正文 >2 MB 拒绝，禁 DTD/实体（防 XXE）；`.pdf`：pypdfium2 逐页，限 1–5 页 |
| 输入上限 | 文件 1 字节–8 MB；PDF ≤5 页 |
| 反幻觉约束 | 提示词要求逐字抄录 `{path, quote}` 证据；**不得计算/推断原文没有的年龄、日期、病史**；不能据数值诊断血糖状态 |
| 资源 | 4B 级多模态模型，需本机可承载 Ollama 推理（显存/内存取决于量化方式，部署时按实际机器记录） |
| 运行验证 | **`pending`**：需在本机 Ollama 下用真实样例（如机构体检资料）跑通并留存输入、输出与人工比对结论；当前仓库内**未见该运行记录文件**，故仅记代码路径已接入，不宣称端到端已验证 |

### 4.4 真实模型问答（#26 已合入 main）

| 项 | 记录 |
| --- | --- |
| 适配器 | `app/llm/openai_compat.OpenAICompatibleLLMProvider`（仅标准库 urllib，无新增依赖） |
| 本次模型 | `deepseek-chat`（OpenAI 兼容 `/chat/completions`，强制 HTTPS） |
| 运行记录 | **`docs/llm-qa-run-record.json`**（由 `backend/scripts/llm_qa_smoke.py` 生成）+ 说明 `docs/LLM_QA_RUN.md` |
| 实测结果 | mode=`model`，耗时约 1.4 s；证据编号故意与输入顺序不一致（EV-9/EV-2/EV-5），模型三条引用全部命中且编号→来源解析正确，无无效引用 |
| 反幻觉约束 | 编号与正文**成对**下发；除"编号必须存在"外，另校验"引用与所引内容不得错位"，错配同样摘除并加注 |

### 4.5 OCR 真实运行记录（PR #20 `feat/report-extraction`，未合并）

| 项 | 记录 |
| --- | --- |
| 环境 | Python 3.12.10 / **pypdfium2 5.13.0**（PDFium 153.0.7999.0） / rapidocr-onnxruntime 1.4.4 / pypdf 6.19.0 |
| 记录文件 | PR #20 分支 `docs/ocr-run-record.json` + 说明 `docs/REPORT_EXTRACTION_OCR_RUN.md` |
| 结果 | `scan_2p` **ok** 1.770 s（2 页全扫描）；`mixed` **ok** 0.477 s；`multi_3p` **partial** 0.850 s（第 3 页 `ocr_empty_result`，显式登记失败页）；`scan_zh`（中文报告扫描件）**ok** 1.213 s |
| 预处理 | pypdfium2 200 dpi 栅格化后交 RapidOCR；逐页登记 `text_layer` / `ocr` / `failed` |
| 已知限制 | 空白页会得 `ocr_empty_result`，按 `partial` 返回并列出失败页，不冒充全文成功；中文 OCR 会归一化掉行内空格，下游须按 token 解析 |

---

## 五、部署前必须确认的许可问题

1. **PyMuPDF 为 AGPL-3.0**。以网络服务形式对外提供时，AGPL 的开源义务需要评估。
   **结论（已落实）**：#20 的 PDF 栅格化**默认后端已由 PyMuPDF 改为 pypdfium2**
   （BSD-3-Clause / Apache-2.0，main 既有智能导入已在用），PyMuPDF 仅作**可选回退**，
   不进入默认部署路径，故不再构成默认方案的许可障碍。
2. **RapidOCR / Qwen 的权重许可单独记录**，不随代码许可：RapidOCR 已按 4.1 固定
   包版本与权重校验值；Qwen 权重清单与运行验证仍为 `pending`，须在部署时补齐。
3. 密钥一律环境变量注入，仓库内不得出现任何凭据（已按此实现）。
4. **T03/T10 接线待完成**：#20（H04）、#21（H05）尚未与 T03（数据入库）和 T10（问答）
   完成真实端到端联调，因此即使代码就绪，也**不得**把本清单的完成状态标成"全部接入完成"。
   待 #20/#21 合入且联调通过后再逐项升格。

---

## 六、明确不在本轮接入

- 原始 CT/MRI 图像的自动检出、分割与诊断模型（任务书明确排除）；
- **H09 任务注册表中 `awaiting_data` 的 LightGBM 疾病风险模型**（需 NLST 训练数据；
  在此之前不产出疾病概率）。

> 边界澄清：上一条**不涉及**参赛版已有的 PREVENT 计算（见 4.2）。PREVENT 是公开发表
> 方程的确定性实现，已在 main 运行并有真实公开数据冒烟记录，本轮不替换、不降级。

---

## 七、新增组件的登记要求

任何新组件接入前必须记录：用途、**代码许可与权重许可（分开）**、权重/制品**不可变版本**
与**下载来源**、**校验值**、资源需求、预处理要求、运行证据（测试或真实样例记录）、
回退与显式不可用行为。**未实际跑通的项必须标 `pending`，不得据代码路径推断为已验证；**
缺任一项不得标 `verified`。
