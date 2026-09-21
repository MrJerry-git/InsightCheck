# 可复用模型/组件清单与接入状态（H10）

负责人：王宏锦（WHJ-2007）。日期：2026-09-21。状态：组件清单与实际接入记录。原则：**OCR/抽取/问答优先接入**；检查权重、许可、预处理、资源与运行证据后才登记"已接入"；不为等待风险模型拖延其余功能（TEAM_TASKS_V2.md 第六节）。

"接入状态"取值：
- `integrated`：已在本仓库代码路径中实际运行，且有测试/运行证据；
- `adapter-ready`：适配器已合入，等待凭据/引擎安装即可运行（不冒充已接入）；
- `evaluated`：完成选型评估，尚未写适配器；
- `not_started`：仅记录候选。

## 一、文件与表格解析

| 组件 | 用途 | 许可 | 接入状态 | 落点与证据 |
| --- | --- | --- | --- | --- |
| Python csv（标准库） | CSV 行读取 | PSF | integrated | T03 文件管理（编码探测归 T03）；解析吃已解出行 |
| openpyxl 3.1 | Excel(.xlsx) 只读值 | MIT | integrated（feat/tabular-parsing） | `app/tabular_parsing/excel.py`；测试 `tests/tabular_parsing/test_excel.py`（真实 xlsx 生成与读取） |
| pypdf 5.x | PDF 文本层抽取 | BSD-3 | integrated（feat/report-extraction） | `app/report_extraction/text_source.py`；测试含自制最小 PDF 夹具（页码/行号验证） |

已知限制：pypdf 对嵌入 CID 字体的中文 PDF 依赖字体 ToUnicode 映射；机构版式中文 PDF 需用真实样例验证（数据到达后在"本机构报告适配"任务中处理）。

## 二、OCR 与影像文字

| 组件 | 用途 | 许可 | 接入状态 | 说明 |
| --- | --- | --- | --- | --- |
| RapidOCR（rapidocr-onnxruntime） | 图片/扫描件 OCR | Apache-2.0；模型权重随包分发 | adapter-ready（feat/report-extraction） | `app/report_extraction/ocr.py` RapidOcrAdapter：延迟导入，未安装时 is_available()=False 并给出安装说明；运行证据待安装引擎后补充 |
| PaddleOCR | 备选 OCR | Apache-2.0 | evaluated | 模型与依赖较重（PaddlePaddle 运行时）；RapidOCR 满足需求时不引入 |
| Tesseract (pytesseract) | 备选 OCR | Apache-2.0（代码）/Apache-2.0 | evaluated | 需系统级二进制安装，Windows 部署成本高；中文需额外语言包 |

OCR 运行证据登记（安装后追加）：引擎版本、测试图片、识别结果与人工比对记录。

## 三、语言模型（问答/解释）

| 组件 | 用途 | 许可/边界 | 接入状态 | 落点与证据 |
| --- | --- | --- | --- | --- |
| local-template | 确定性结构化解释 | 无外部依赖 | integrated（feat/llm-qa-service） | `app/llm/templated.py`；显式标注模板模式 |
| OpenAI 兼容聊天接口（任意供应商） | 真实模型问答 | 供应商条款；密钥不进 Git | adapter-ready（feat/llm-qa-service） | `app/llm/openai_compat.py`；强制 HTTPS、显式错误、引用守卫（`app/llm/qa.py`）；待凭据申请后联调 |
| DeepFM（本项目自实现） | Patient×ExamItem 匹配排序 | 项目内代码 | integrated（1.0 既有，合成演示） | `app/ml/recommendation/`；仅合成演示运行，真实制品未接入（见 H09 注册表） |

## 四、模型与统计组件

| 组件 | 用途 | 许可 | 接入状态 | 说明 |
| --- | --- | --- | --- | --- |
| torch | DeepFM 网络推理/训练 | BSD-3 | integrated（1.0 既有） | 运行依赖；CPU 可运行 |
| LightGBM | 疾病风险模型（未来） | MIT | not_started | 接入路径保留：H09 任务注册表 + TaskAdapter 槽位；数据到达后按任务卡训练 |
| scikit-learn | 基线实验 | BSD-3 | integrated（research extra） | 离线实验程序 `app/research/`；不进在线服务 |
| numpy | 数值计算 | BSD-3 | integrated | 运行依赖 |

## 五、明确不在本轮接入

- 原始 CT/MRI 图像的自动检出、分割与诊断模型（任务书明确排除）；
- 疾病风险概率输出（无训练数据；H09 注册表显式 awaiting_data）。

## 六、新增组件的登记要求

任何新组件接入前必须记录：用途、许可证兼容性、权重/资源需求、预处理要求、运行证据（测试或真实样例记录）、回退与显式不可用行为。缺任何一项不得标 `integrated`。
