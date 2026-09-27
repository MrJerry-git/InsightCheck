import type { Report } from "../prevention/types";

export type SystemKey = "heart" | "metabolic" | "kidney";
export const systems = {
  heart: { name: "心血管健康", english: "CARDIOVASCULAR", short: "心血管", description: "从每一次测量，了解心血管的长期变化。", metrics: ["sbp", "total_c", "hdl_c"], codes: ["bp", "lipids"], color: "#df7059" },
  metabolic: { name: "血糖与代谢", english: "GLUCOSE & METABOLISM", short: "血糖与代谢", description: "连接历年的血糖记录，让下一次检查更有依据。", metrics: ["fasting_glucose", "hba1c", "bmi"], codes: ["glucose"], color: "#c89a40" },
  kidney: { name: "肾功能", english: "KIDNEY HEALTH", short: "肾功能", description: "回看肾功能指标，明确需要关注的随访安排。", metrics: ["egfr"], codes: ["kidney"], color: "#aa7f9c" },
} as const;
export const labels: Record<string, string> = { sex: "生理性别", known_cvd: "已确诊心血管疾病", pregnant: "当前妊娠", symptomatic: "当前不适", date: "检查日期", age: "检查时年龄", sbp: "收缩压", total_c: "总胆固醇", hdl_c: "HDL 胆固醇", chol_unit: "胆固醇单位", bmi: "BMI", egfr: "eGFR", dm: "糖尿病病史", smoking: "当前吸烟", bp_tx: "使用降压药", statin: "使用他汀", hba1c: "HbA1c", fasting_glucose: "空腹血糖", glucose_status: "既有血糖结论" };
export const units: Record<string, string> = { age: "岁", sbp: "mmHg", bmi: "kg/m²", egfr: "mL/min/1.73m²", hba1c: "%", fasting_glucose: "mmol/L" };
export function display(value: unknown) { return value === null || value === undefined || value === "" ? "待补充" : value === true ? "是" : value === false ? "否" : ({ female: "女", male: "男", normal: "已确认正常", prediabetes: "已确认糖尿病前期", diabetes: "已确诊糖尿病", unknown: "未确认" }[String(value)] ?? String(value)); }
export function coverage(report: Report | null, key: SystemKey) {
  return !!report?.input.visits.some(v => systems[key].metrics.some(field => v[field as keyof typeof v] !== null && v[field as keyof typeof v] !== undefined));
}
export function recommendations(report: Report, key: SystemKey | "all") {
  const seen = new Set<string>();
  return report.recommendations.filter(item => {
    const included = key === "all" || item.code === "clinical" || (systems[key].codes as readonly string[]).includes(item.code);
    if (!included || seen.has(item.code)) return false;
    seen.add(item.code); return true;
  });
}
export function today() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
export function localDate(value: string) {
  const d = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(d.getTime()) ? value.slice(0, 10) : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/prevention${path}`, body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let data;
  try { data = await response.json(); } catch { throw new Error("服务暂时未连接，请稍后重试。已保存的资料不会被更改。"); }
  if (!response.ok) {
    if (Array.isArray(data.detail)) throw new Error("资料尚未通过校验，请检查日期、必填项、单位及病史是否一致后补充说明。");
    throw new Error(typeof data.detail === "string" ? data.detail.replace("或改用手动录入", "并补充说明后重试") : "请求未完成，请重试。");
  }
  return data;
}
