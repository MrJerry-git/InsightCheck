# 比赛版：体检资料智能导入

本功能用本地 Qwen3-VL 提取资料，不训练新模型，不替代 PREVENT 计算或推荐规则。
默认 `qwen3-vl:4b-instruct`（Ollama Q4_K_M，约 3.3 GB 下载），适合先在本机测试。
请保留 `-instruct` 后缀：本次实测默认 `:4b` 使用 Thinking 模板，结构化输出不兼容。
内存/显存用量高于下载大小，实际速度取决于页数、分辨率和设备。

## 启动

1. 按 README 安装/更新后端依赖（新增 Pillow、pypdfium2，httpx 成为运行依赖）。
2. 双击根目录 `start-smart-import.cmd`。首次联网下载 Ollama 与模型，需要数 GB 磁盘空间。
   便携程序、模型和日志保存在忽略目录 `.runtime/ollama`；Ollama 自身会在用户目录创建配置。
   若复用已运行的 Ollama，模型保存在那个服务自身的模型目录。
3. 启动或重启比赛版：`start-competition.cmd`，打开 `/competition`。
4. 点击“检查模型状态”，就绪后上传文件或粘贴文字，点击 AI 提取。
5. 对照原件核对提取结果，补齐必填缺项，勾选核对声明，确认填入档案，再生成评估。

安装后无需互联网完成推理。原始文件不会写入数据库或磁盘；已确认的结构化数据仅在
用户保存规划报告时随既有报告快照保存。当前仍为本地无账号隔离比赛版。
不能把前端或 Ollama 服务直接暴露到公网。

换模型：运行 `powershell -ExecutionPolicy Bypass -File start-smart-import.ps1 -Model qwen3-vl:2b-instruct`
并在 `.env` 设置 `IMPORT_MODEL=qwen3-vl:2b-instruct`，重启后端。4B、2B 的提取效果需分别验证。
运行模型与网页服务分开；关闭比赛网页不会停止 Ollama。
可运行 `.runtime/ollama/ollama.exe stop qwen3-vl:4b-instruct` 卸载显存中的模型；下一次请求会重新加载。

## 输入与限制

- 粘贴文字 / UTF-8 TXT：最多 16000 字符。
- DOCX：读取正文和表格文字；不识别嵌入图片、不执行宏、不处理旧版 DOC。
- PDF：最多 5 页，逐页渲染给视觉模型，包括扫描版；不支持加密文件。
- PNG、JPEG、WebP：单张，最多 2000 万像素，推理前最长边缩至 1800。
- 单文件最多 8 MB；超限明确拒绝，不截断页数或文字。
- 每次最多 10 条历史记录，仅同一人；不自动跨人合并。

提取内容包括日期、年龄、性别、收缩压、胆固醇及单位、BMI、eGFR、HbA1c、空腹血糖、
已有病史/用药/血糖结论。未提及的信息保持空值；不能把未提及解释为“否”。
不根据数值诊断糖尿病、不从其他数值推算 BMI/eGFR、不推断检查日期。

每项显示模型摘录的原文。纯文本模式中，摘录不在原文或无摘录时清空该字段。
图片摘录不是经过独立 OCR 认证的证据，仍需对照原件。即使摘录存在，也不能保证
字段与摘录语义对应正确，因此所有导入都必须人工核对。确认后复用现有服务端输入校验，
未补齐必填项、矛盾日期/病史或越界数据不能进入评估。

## 接口

- GET `/api/v1/prevention/smart-import/status`：模型是否安装、服务是否在线。
- POST `/api/v1/prevention/smart-import/extract`：`{text, file?: {name, content: base64}}`。
  返回 `draft/evidence/missing/warnings`（warnings 位于 draft）、模型名称和待确认标记，不保存报告。
- POST `/api/v1/prevention/smart-import/confirm`：`{confirmed: true, intake: ...}`。
  返回已通过现有 PreventionRequest 校验的 intake，前端再交给原评估流程。

模型不可用返回 503，处理超时返回 504，输入/输出非法返回 422，忙时返回 429。
每个后端进程同时仅处理一次提取，比赛版使用单 worker。
模型只有提取能力，无工具调用，不执行资料中的指令；输出仍作为不可信草稿处理。

## 许可与来源

- 官方权重：https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct （Apache-2.0）。
- 量化分发：https://ollama.com/library/qwen3-vl:4b-instruct （页面标注 Apache-2.0）。
- Ollama：https://github.com/ollama/ollama （MIT）。
- Pillow：https://github.com/python-pillow/Pillow （HPND）。
- pypdfium2：https://github.com/pypdfium2-team/pypdfium2 （Apache-2.0/BSD-3-Clause，
  底层 PDFium 及随包依赖另附许可证，分发时须保留）。

模型权重和运行程序不提交到 GitHub。分发离线安装包时需附各上游许可与 notices。
本功能的可用性测试不等于真实体检报告识别准确率研究，也不代表临床验证。

## 复现检查

后端：`.venv/Scripts/python.exe -m pytest tests/test_smart_import.py`。
已启动模型时可运行 `.venv/Scripts/python.exe scripts/smoke_smart_import.py`，
使用仓库内明确标注的人工资料及程序生成的图片/PDF，结果写入忽略目录 `.runtime`。
页面体验可上传 [人工演示资料](examples/smart-import-demo.txt)，资料来源请选择“人工构造示例”。
样例日期固定为 2026-09-20，后续过期时请更新演示日期并核对年龄。

## 本机实测（2026-09-20）

- Ollama 0.34.2，`qwen3-vl:4b-instruct`，Q4_K_M。
- 模型层 SHA256：`16b83be682148a4d8201dbf720ea7eace5de98b69f63f05e0c908b4d7977ecb5`。
- 8 GB NVIDIA 笔记本显卡；一次运行的文字/PNG/扫描 PDF 分别约 14.58/16.44/10.64 秒。
- 人工文字样例必填项完整；图片和 PDF 的收缩压及胆固醇数值提取断言通过。
  图片/PDF 的胆固醇单位缺少有效依据，仍需补充确认；未写出的吸烟与用药状态保持为空。
- 全套后端 273 项测试通过；前端 2 项测试、类型检查、lint、生产构建通过。
- 浏览器完成真实本地模型文字提取、原文核对、标记人工示例、确认填入档案、生成风险与年度建议。

上述时间是少量人工样例的一次实测，不是性能保证或真实报告准确率指标。
