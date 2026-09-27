"""Real local model smoke check; synthetic fixtures, not an accuracy benchmark.

Run from backend: .venv/Scripts/python.exe scripts/smoke_smart_import.py
"""

import base64
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.smart_import import ImportRequest  # noqa: E402
from app.services.smart_import import extract  # noqa: E402

root = Path(__file__).resolve().parents[2]
text = (root / "docs/examples/smart-import-demo.txt").read_text(encoding="utf-8")
started = time.monotonic()
result = extract(ImportRequest(text=text))
visit = result["draft"]["visits"][0]
assert result["draft"]["sex"] == "female", result
assert visit["date"] == "2026-09-20", result
assert visit["sbp"] == 130, result
assert visit["total_c"] == 5.2, result
assert visit["hdl_c"] == 1.3, result
assert visit["dm"] is False, result
audit = [{"fixture": "synthetic_text", "seconds": round(time.monotonic() - started, 2),
          "result": result}]

# Generate a known synthetic image; no patient documents are read.
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

font_path = Path("C:/Windows/Fonts/msyh.ttc")
if not font_path.exists():
    raise SystemExit("Set an available Chinese font in this Windows smoke script.")
img = Image.new("RGB", (1200, 700), "white")
draw = ImageDraw.Draw(img)
font = ImageFont.truetype(str(font_path), 32)
lines = ["人工构造测试报告 / 非真实患者", "性别：女", "检查日期：2026-09-20", "检查时年龄：50岁",
         "收缩压：130 mmHg", "总胆固醇：5.2 mmol/L", "高密度脂蛋白胆固醇：1.3 mmol/L"]
for i, line in enumerate(lines):
    draw.text((50, 40 + i * 70), line, font=font, fill="black")
for extension, format_name in [("png", "PNG"), ("pdf", "PDF")]:
    buffer = io.BytesIO()
    img.save(buffer, format=format_name)
    started = time.monotonic()
    result = extract(ImportRequest(file={"name": f"synthetic.{extension}",
        "content": base64.b64encode(buffer.getvalue()).decode()}))
    visit = result["draft"]["visits"][0]
    assert visit["sbp"] == 130, result
    assert visit["total_c"] == 5.2, result
    assert visit["smoking"] is None, result
    assert visit["bp_tx"] is None, result
    audit.append({"fixture": f"synthetic_{extension}",
                  "seconds": round(time.monotonic() - started, 2), "result": result})
output = root / ".runtime/smart-import-smoke.json"
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps([{"fixture": a["fixture"], "seconds": a["seconds"],
                   "missing": a["result"]["missing"]} for a in audit], ensure_ascii=False))
