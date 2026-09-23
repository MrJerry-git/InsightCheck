# H04 OCR 实际运行记录（2026-09-22）

应 PR #20 审核意见「补充全扫描、文字+扫描混合、多页的真实文件测试，并提交实际
OCR 运行记录（版本、样例、结果与人工核对）」生成。

## 复现方式

```bash
pip install pymupdf rapidocr-onnxruntime   # 引擎未安装时脚本报错，不生成伪造记录
python backend/scripts/ocr_smoke.py        # 结果写入 docs/ocr-run-record.json
```

## 运行环境

| 项 | 值 |
| --- | --- |
| 生成时间（UTC） | 2026-09-22T09:02:58Z |
| Python / 平台 | 3.12.10 / Windows-11-10.0.26200-SP0 |
| OCR 引擎 | rapidocr-onnxruntime 1.4.4 |
| PDF 渲染器 | pymupdf 1.27.2.3 |
| 文本层解析 | pypdf 6.19.0 |

## 样例构造

样例由 `backend/scripts/ocr_smoke.py` 现场生成：先把已知文字绘制成页面，再光栅化
（200 DPI）后重新嵌入 PDF，得到**无文本层的扫描页**；混合样例另含一页真实文本层。

已知真值（ground truth）：

1. `Total Cholesterol 5.2 mmol/L`
2. `Fasting Glucose 6.1 mmol/L`

## 运行结果与人工核对

| 样例 | 页面构成 | 状态 | 逐页结果 | 耗时 |
| --- | --- | --- | --- | --- |
| scan_2p.pdf | 2 页全扫描 | ok | 1=ocr、2=ocr | 2.314 s |
| mixed.pdf | 第 1 页文本层 + 第 2 页扫描 | ok | 1=text_layer、2=ocr | 0.688 s |
| multi_3p.pdf | 第 1 页文本层 + 第 2 页扫描 + 第 3 页空白图 | **partial** | 1=text_layer、2=ocr、3=failed（ocr_empty_result） | 1.365 s |

人工核对（OCR 输出 vs 真值）：

| 页 | OCR 输出 | 真值 | 核对结论 |
| --- | --- | --- | --- |
| scan_2p p1/p2 | `Total Cholesterol 5.2 mmol/L` / `Fasting Glucose 6.1 mmol/L` | 同左 | 完全一致 |
| mixed p1 | `Lab Report WBC 6.2 10*9/L 3.5-9.5` | 文本层真值 | 完全一致（走文本层，未 OCR） |
| mixed p2 / multi p2 | `Total Cholesterol 5.2 mmol/L` / `Fasting Glucose 6.1 mmol/L` | 同左 | 完全一致 |
| multi p3 | 无输出，页面登记为 failed（ocr_empty_result） | 空白页 | 符合预期：空白页不会被伪造为成功 |

关键结论：

1. 全扫描 PDF 在注入可用引擎后**逐页调用 OCR**并抽取到文本，不再整体返回
   `needs_ocr`（修复前的行为）。
2. 混合 PDF 的无文本页不再被静默跳过，第 2 页被逐页渲染并 OCR。
3. 无法处理的页（空白页）显式登记为 `failed`，整份文档状态为 `partial`
   而不是 `ok`。

## 局限（不扩大解释）

- 样例为人工构造的打印体英文文本，**不是真实机构报告**；中文版式、模糊扫描、
  复杂表格的识别质量尚未形成代表性评测，仍需人工核对。
- 耗时仅为本机单次运行观察值，不构成性能保证。
- 引擎许可：rapidocr-onnxruntime 为 Apache-2.0，PyMuPDF 为 AGPL-3.0（商用需评估）；
  具体许可依据同时登记在 `docs/REUSABLE_COMPONENTS.md`。
