"""Optional reproducibility tool; pip install pyreadr (not a runtime dependency)."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

import pyreadr

REVISION = "ebe2ac15c38569c3bdaf871c4853b6eeff77b039"
root = Path(__file__).resolve().parents[2]
path = root / ".runtime" / "prevent-audit" / "sysdata.rda"
path.parent.mkdir(parents=True, exist_ok=True)
if not path.exists():
    with urlopen(f"https://raw.githubusercontent.com/martingmayer/preventr/{REVISION}/R/sysdata.rda",
                 timeout=45) as response:
        path.write_bytes(response.read())
data = pyreadr.read_r(str(path))
models = {}
for model in ("base", "hba1c"):
    for years in (10, 30):
        key = f"{model}_{years}yr"
        table = data[key]
        models[key] = {c: table[c].to_list() for c in table.columns
                       if c.endswith(("total_cvd", "ascvd", "heart_failure"))}
result = {"upstream": "https://github.com/martingmayer/preventr", "revision": REVISION,
          "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "models": models}
(root / "backend/app/services/prevent_coefficients.json").write_text(
    json.dumps(result, indent=2) + "\n", encoding="utf-8"
)
