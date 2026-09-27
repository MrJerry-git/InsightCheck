# 比赛版第三方来源与许可

## preventr

本项目的 `backend/app/services/prevent_equations.py` 为 preventr 中
`prep_terms` / `run_models` 的 Python 移植；`prevent_coefficients.json` 中的
基础与 HbA1c 增强方程系数从其 `R/sysdata.rda` 提取，未重新训练或修改系数。

- 项目：https://github.com/martingmayer/preventr
- 作者：Martin Mayer / preventr authors
- 固定版本：0.12.0
- 固定提交：ebe2ac15c38569c3bdaf871c4853b6eeff77b039
- 上游 DESCRIPTION 声明 `MIT + file LICENSE`；LICENSE 指定 2024、preventr authors。
- 原始系数 SHA-256 记录在 JSON 文件；复现脚本见 `backend/scripts/extract_prevent_coefficients.py`。
- 本版只暴露 CVD、ASCVD、HF 三个结局，不拼接修改风险方程。

MIT License

Copyright (c) 2024 preventr authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

## PREVENT 方程、官方材料与商用边界

科学来源：Khan SS et al. Development and Validation of the American Heart
Association Predicting Risk of Cardiovascular Disease EVENTs (PREVENT) Equations.
Circulation. DOI: 10.1161/CIRCULATIONAHA.123.067626。
科学声明 DOI: 10.1161/CIR.0000000000001191。

本仓库没有复制 AHA 受协议管理的官方代码、Logo 或网页，也未代用户接受其协议。
本次使用公开 MIT 第三方实现，不表示取得 AHA 背书或对所有商业模式的法律许可。
官方代码协议：https://www.jotform.com/240774577352161
该协议允许嵌入更大方案和间接商业变现，但禁止直接售卖/收费使用风险计算器、
诊断用途、独立治疗决策、修改组合版风险方程等。若后续采用官方材料或商业发布，
应按实际使用方式核查协议并完成必要授权，不能仅以第三方 MIT 代替。

## 指南与数据

推荐模块是 InsightCheck 自行实现的规则，与 PREVENT 风险计算独立版本化。
仅摘述规则并链接来源，不复制完整指南；不声称获得指南机构认可。
NHANES 审计使用 CDC 公开匿名数据；不提交下载的个体记录，只提交下载地址、
校验和、字段映射、聚合计数与复现程序。不得尝试识别或关联个人身份。
# 智能资料导入新增组件

本地推理使用 Qwen3-VL-4B-Instruct 的 Ollama 量化分发 `qwen3-vl:4b-instruct`。
官方权重与量化模型页面标注 Apache-2.0；原模型归 Qwen 团队所有，未修改权重，
不声称官方背书。权重不包含在本仓库内。
来源：https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct
量化：https://ollama.com/library/qwen3-vl:4b-instruct
许可证：https://www.apache.org/licenses/LICENSE-2.0

新增文档读取依赖 Pillow（HPND）、pypdfium2（Apache-2.0/BSD-3-Clause，PDFium
随包第三方 notices 亦须保留）；Ollama 运行程序为 MIT，单独下载。
重新分发时保留相关版权、许可证、NOTICE，并标注对上游文件的修改。
本仓库自己的接入代码不代表重新授予上游商标或医疗用途认证。
