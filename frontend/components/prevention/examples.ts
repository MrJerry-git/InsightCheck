import type { Intake } from "./types";

export function example(kind: "normal" | "prediabetes" | "diabetes" = "prediabetes"): Intake {
  const now = new Date();
  const day = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const dates = [2, 1, 0].map(years => `${now.getFullYear() - years}-${day.slice(5) === "02-29" ? "02-28" : day.slice(5)}`);
  return {
    label: `示例：${kind === "normal" ? "正常筛查随访" : kind === "diabetes" ? "已有糖尿病" : "糖尿病前期随访"}`,
    sex: "female", known_cvd: false, pregnant: false, symptomatic: false,
    source: "synthetic", source_note: "人工构造的流程演示病例，不是真实患者，不用于证明效果。", as_of: day,
    visits: dates.map((date, i) => ({
      date, age: 48 + i, sbp: kind === "normal" ? 115 : 130 + 5 * i,
      total_c: 5.2, hdl_c: 1.3, chol_unit: "mmol/L", bmi: 27,
      egfr: 95 - i * 2, dm: kind === "diabetes", smoking: false,
      bp_tx: kind === "diabetes", statin: false,
      hba1c: kind === "normal" ? 5.2 : kind === "diabetes" ? 7.2 : Number((5.8 + i * 0.1).toFixed(1)),
      fasting_glucose: kind === "normal" ? 5.0 : kind === "diabetes" ? 7.5 : Number((5.8 + i * 0.1).toFixed(1)),
      glucose_status: kind,
    })),
  };
}

export function manual(): Intake {
  const base = example();
  return { ...base, label: "", sex: "", source: "manual", source_note: "",
    known_cvd: null, pregnant: null, symptomatic: null,
    visits: [{ date: "", age: null, sbp: null, total_c: null, hdl_c: null,
      chol_unit: "mmol/L", bmi: null, egfr: null, dm: null, smoking: null,
      bp_tx: null, statin: null, hba1c: null, fasting_glucose: null, glucose_status: "unknown" }],
  };
}
