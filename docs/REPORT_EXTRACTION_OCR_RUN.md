# H04 OCR 实际运行记录（2026-09-27）

应 PR #20 审核意见「补充全扫描、文字+扫描混合、多页的真实文件测试，并提交实际
OCR 运行记录（版本、样例、结果与人工核对）」生成；本次按复核意见把渲染后端由
PyMuPDF（**AGPL-3.0**）换成 pypdfium2（**BSD-3-Clause / Apache-2.0**，与 main 既有
智能导入同一依赖），并重跑记录。

## 复现方式

```bash
pip install -e '.[ocr]'                 # pypdfium2 + rapidocr-onnxruntime
python backend/scripts/ocr_smoke.py     # 结果写入 docs/ocr-run-record.json
```

引擎未安装时脚本**明确报错、不生成伪造记录**；样例 PDF 由 Pillow + 手写 PDF 结构
现场构造，不依赖 PyMuPDF。

## 运行环境

| 项 | 值 |
| --- | --- |
| 生成时间（UTC） | 2026-09-27T12:25:03Z |
| Python / 平台 | 3.12.10 / Windows-11-10.0.26200-SP0 |
| OCR 引擎 | rapidocr-onnxruntime 1.4.4（Apache-2.0） |
| PDF 渲染器 | pypdfium2 5.13.0（BSD-3-Clause / Apache-2.0） |
| 文本层解析 | pypdf 6.19.0 |

## 样例构造

样例由 `backend/scripts/ocr_smoke.py` 现场生成：用 Pillow 把已知文字画成图片，
以 FlateDecode 原始 RGB 直接嵌入 PDF，得到**无文本层的扫描页**；混合样例另含一页
真实文本层，多页样例额外含一张空白图页（用于验证失败页被显式登记）。中文样例用
系统中文字体（Microsoft YaHei / 黑体 / Noto Sans CJK）绘制，找不到字体时该样例
被**显式跳过**并在记录 `notes` 中注明，不伪造结果。

已知真值（ground truth）：

| 语言 | 真值 |
| --- | --- |
| 英文 | `Total Cholesterol 5.2 mmol/L`、`Fasting Glucose 6.1 mmol/L` |
| 中文 | `血常规检验报告`、`血红蛋白 135 g/L`、`空腹血糖 5.2 mmol/L` |

## 运行结果与人工核对

| 样例 | 页面构成 | 状态 | 逐页结果 | 耗时 |
| --- | --- | --- | --- | --- |
| scan_2p.pdf | 2 页全扫描（英文） | ok | 1=ocr、2=ocr | 1.770 s |
| mixed.pdf | 第 1 页文本层 + 第 2 页扫描 | ok | 1=text_layer、2=ocr | 0.477 s |
| multi_3p.pdf | 第 1 页文本层 + 第 2 页扫描 + 第 3 页空白图 | **partial** | 1=text_layer、2=ocr、3=failed（ocr_empty_result） | 0.850 s |
| scan_zh.pdf | 1 页全扫描（中文） | ok | 1=ocr | 1.213 s |

人工核对（OCR 输出 vs 真值）：

| 页 | OCR 输出 | 真值 | 核对结论 |
| --- | --- | --- | --- |
| scan_2p p1/p2 | `Total Cholesterol 5.2 mmol/L` / `Fasting Glucose 6.1 mmol/L` | 同左 | 完全一致 |
| mixed p1 | `Lab Report WBC 6.2 10*9/L 3.5-9.5` | 文本层真值 | 完全一致（走文本层，未 OCR） |
| mixed p2 / multi p2 | `Total Cholesterol 5.2 mmol/L` / `Fasting Glucose 6.1 mmol/L` | 同左 | 完全一致 |
| scan_zh p1 | `血常规检验报告` / `血红蛋白135g/L` / `空腹血糖5.2mmol/L` | `血常规检验报告` / `血红蛋白 135 g/L` / `空腹血糖 5.2 mmol/L` | 项目名/数值/单位 token 全部一致；行内空格被引擎归一化掉（RapidOCR 常见行为，属预期） |
| multi p3 | 无输出，页面登记为 failed（ocr_empty_result） | 空白页 | 符合预期：空白页不会被伪造为成功 |

关键结论：

1. 全扫描 PDF 在注入可用引擎后**逐页调用 OCR**并抽取到文本，不再整体返回
   `needs_ocr`（修复前的行为）。
2. 混合 PDF 的无文本页不再被静默跳过，第 2 页被逐页渲染并 OCR。
3. 无法处理的页（空白页）显式登记为 `failed`，整份文档状态为 `partial`
   而不是 `ok`。
4. 更换渲染后端（PyMuPDF → pypdfium2）后英文识别结果与旧记录**逐字一致**，
   说明渲染等价、无回归；中文报告样例亦被正确识别。

## 局限（不扩大解释）

- 样例为人工构造的打印体文本（含一页中文），**不是真实机构报告**；中文版式的
  表格/印章/模糊扫描识别质量尚未形成代表性评测，仍需人工核对。
- 行内空格在中文 OCR 输出中可能被归一化掉，下游结构化（H03）需按 token 解析
  而非依赖空格；本记录如实呈现该行为。
- 耗时仅为本机单次运行观察值，不构成性能保证。
- 引擎许可：pypdfium2 为 BSD-3-Clause / Apache-2.0、rapidocr-onnxruntime 为
  Apache-2.0，均可用于商用；PyMuPDF 为 AGPL-3.0（商用需评估），仅作可选回退，
  **不是默认方案**。具体许可依据同时登记在 `docs/REUSABLE_COMPONENTS.md`。
