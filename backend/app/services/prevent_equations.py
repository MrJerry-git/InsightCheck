"""Python port of preventr 0.12.0 prep_terms/run_models (MIT).

Source revision and unmodified coefficients are in prevent_coefficients.json.
Only the published base/HbA1c models and three primary outcomes are exposed.
"""

import json
import math
from pathlib import Path

from app.schemas.prevention import Visit

COEFFICIENTS = json.loads(Path(__file__).with_name("prevent_coefficients.json").read_text())
MODEL_VERSION = "preventr-0.12.0-python-1"


def eligibility(v: Visit) -> list[str]:
    multiplier = 1 if v.chol_unit == "mg/dL" else 1 / 0.02586
    checks = {
        "年龄": (v.age, 30, 79), "收缩压": (v.sbp, 90, 200),
        "总胆固醇 mg/dL": (v.total_c * multiplier, 130, 320),
        "HDL mg/dL": (v.hdl_c * multiplier, 20, 100),
        "BMI": (v.bmi, 18.5, 39.9), "eGFR": (v.egfr, 15, 140),
    }
    if v.hba1c is not None:
        checks["HbA1c %"] = (v.hba1c, 4.5, 15)
    return [f"{name}超出模型范围 {lo}–{hi}" for name, (x, lo, hi) in checks.items()
            if not lo - 1e-8 <= x <= hi + 1e-8]


def calculate(v: Visit, sex: str) -> dict:
    if eligibility(v):
        raise ValueError("; ".join(eligibility(v)))
    age = (v.age - 55) / 10
    conv = 0.02586 if v.chol_unit == "mg/dL" else 1
    non_hdl = (v.total_c - v.hdl_c) * conv - 3.5
    hdl = (v.hdl_c * conv - 1.3) / 0.3
    sbp_hi = (max(v.sbp, 110) - 130) / 20
    bmi_hi = (max(v.bmi, 30) - 30) / 5
    egfr_lo = (min(v.egfr, 60) - 60) / -15
    values = [age, non_hdl, hdl, (min(v.sbp, 110) - 110) / 20, sbp_hi,
              int(v.dm), int(v.smoking), (min(v.bmi, 30) - 25) / 5, bmi_hi,
              egfr_lo, (max(v.egfr, 60) - 90) / -15, int(v.bp_tx), int(v.statin),
              v.bp_tx * sbp_hi, v.statin * non_hdl, age * non_hdl, age * hdl,
              age * sbp_hi, age * v.dm, age * v.smoking, age * bmi_hi, age * egfr_lo]
    model = "hba1c" if v.hba1c is not None else "base"
    if v.hba1c is not None:
        values += [(v.hba1c - 5.3) if v.dm else 0,
                   (v.hba1c - 5.3) if not v.dm else 0, 0]
    output = {"variant": model, "version": MODEL_VERSION, "horizons": {}}
    for years in ([10, 30] if v.age <= 59 else [10]):
        terms = values.copy()
        if years == 30:
            terms.insert(1, age ** 2)
        terms.append(1)
        outcomes = {}
        for outcome in ("total_cvd", "ascvd", "heart_failure"):
            weights = COEFFICIENTS["models"][f"{model}_{years}yr"][f"{sex}_{outcome}"]
            logit = sum(a * b for a, b in zip(terms, weights, strict=True))
            outcomes[outcome] = 1 / (1 + math.exp(-logit))
        output["horizons"][str(years)] = outcomes
    return output
