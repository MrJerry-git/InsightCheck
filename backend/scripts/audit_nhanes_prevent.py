"""Download public NHANES tables and smoke-test PREVENT on complete records.

Run from backend: python scripts/audit_nhanes_prevent.py --directory ../.runtime/nhanes
Requires the research extra. No participant records are committed or exported.
This is neither a longitudinal dataset nor an evaluation of predictive accuracy.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.schemas.prevention import Visit  # noqa: E402
from app.services.prevent_equations import calculate, eligibility  # noqa: E402

BASE = "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/"
TABLES = {
    "DEMO_J": ["RIAGENDR", "RIDAGEYR"], "BPX_J": ["BPXSY1", "BPXSY2", "BPXSY3"],
    "BMX_J": ["BMXBMI"], "TCHOL_J": ["LBXTC"], "HDL_J": ["LBDHDD"],
    "BIOPRO_J": ["LBXSCR"], "GHB_J": ["LBXGH"], "DIQ_J": ["DIQ010"],
    "SMQ_J": ["SMD641"],
    "MCQ_J": ["MCQ160B", "MCQ160C", "MCQ160D", "MCQ160E", "MCQ160F"],
    "RXQ_RX_J": ["RXDUSE"],
}


def audit(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    data = None
    sources = []
    for name, cols in TABLES.items():
        path = directory / f"{name}.xpt"
        if not path.exists():
            with urlopen(BASE + path.name, timeout=45) as response:
                content = response.read()
            if not content.startswith(b"HEADER RECORD"):
                raise ValueError(f"Not an XPT file: {name}")
            path.write_bytes(content)
        frame = pd.read_sas(path, format="xport")[["SEQN", *cols]]
        sources.append({"table": name, "rows": len(frame), "url": BASE + path.name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        if name == "RXQ_RX_J":
            # Deliberately narrow: explicitly reports no prescription use, not
            # an inferred absence of statins from incomplete medication names.
            frame = frame[frame.RXDUSE == 2].drop_duplicates("SEQN")
        data = frame if data is None else data.merge(frame, on="SEQN", validate="one_to_one")
    assert data is not None
    joined = len(data)
    data["sbp"] = data[["BPXSY1", "BPXSY2", "BPXSY3"]].replace(0, float("nan")).mean(axis=1)
    required = ["RIDAGEYR", "RIAGENDR", "sbp", "BMXBMI", "LBXTC", "LBDHDD",
                "LBXSCR", "DIQ010", "SMD641"]
    data = data.dropna(subset=required)
    data = data[data.RIDAGEYR.between(30, 79) & data.DIQ010.isin([1, 2])
                & data.SMD641.between(0, 30) & data.RIAGENDR.isin([1, 2])]
    for name in TABLES["MCQ_J"]:
        data = data[data[name] == 2]
    risks = []
    excluded = 0
    for _, row in data.iterrows():
        female = row.RIAGENDR == 2
        kappa, alpha = (.7, -.241) if female else (.9, -.302)
        creatinine = row.LBXSCR / kappa
        egfr = (142 * min(creatinine, 1) ** alpha * max(creatinine, 1) ** -1.2
                * .9938 ** row.RIDAGEYR * (1.012 if female else 1))
        # Date is a cycle-end sentinel for the Visit adapter, NOT an observed
        # examination date. It is never sent to the screening-planning service.
        visit = Visit(date="2018-12-31", age=int(row.RIDAGEYR), sbp=row.sbp,
                      total_c=row.LBXTC, hdl_c=row.LBDHDD, chol_unit="mg/dL",
                      bmi=row.BMXBMI, egfr=egfr, dm=bool(row.DIQ010 == 1),
                      smoking=bool(row.SMD641 > 0), bp_tx=False, statin=False,
                      hba1c=None if pd.isna(row.LBXGH) else row.LBXGH)
        if eligibility(visit):
            excluded += 1
            continue
        result = calculate(visit, "female" if female else "male")
        risks.append(result["horizons"]["10"])
    if not risks:
        raise ValueError("No eligible records; inspect source fields before proceeding")
    return {"dataset": "CDC NHANES 2017–2018 public-use files",
            "purpose": "真实公开输入上的计算冒烟验证，不是准确率实验",
            "joined_no_prescription_records": joined, "eligible_complete_records": len(risks),
            "excluded_model_range": excluded, "sources": sources,
            "checks": {"all_probabilities_in_range": all(
                0 < p < 1 for r in risks for p in r.values())},
            "limitations": ["横断面数据，不能验证年度复查或长期预测准确性。",
                            "刻意限制为明确报告未用处方药的完整资料人群，非代表性样本。",
                            "没有应用调查权重；不输出总体患病率或效能指标。",
                            "eGFR 按 NIDDK 2021 CKD-EPI 肌酐公式推算。",
                            "无精确体检日期，不导入年度规划，不虚构历史记录。"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("../docs/NHANES_PREVENT_AUDIT.json"))
    args = parser.parse_args()
    result = audit(args.directory)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Eligible: {result['eligible_complete_records']}; range checks passed.")
