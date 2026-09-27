"use client";

import { useState } from "react";
import type { Intake } from "./types";

type Value = string | number | boolean | null;
type Row = Record<string, Value>;
type Extraction = {
  draft: { sex: Value; known_cvd: Value; pregnant: Value; symptomatic: Value; visits: Row[]; warnings: string[] };
  evidence: Record<string, string>; missing: string[]; model: string; note: string;
};
const labels: Record<string, string> = {
  sex: "生理性别", known_cvd: "已确诊心血管疾病", pregnant: "当前妊娠", symptomatic: "当前不适",
  date: "检查日期", age: "检查时年龄", sbp: "收缩压（mmHg）", total_c: "总胆固醇",
  hdl_c: "HDL 胆固醇", chol_unit: "两项胆固醇的单位", bmi: "BMI（kg/m²）",
  egfr: "eGFR（mL/min/1.73m²）", dm: "糖尿病病史", smoking: "当前吸烟",
  bp_tx: "使用降压药", statin: "使用他汀", hba1c: "HbA1c（%，可选）",
  fasting_glucose: "空腹血糖（mmol/L，可选）", glucose_status: "已有血糖结论",
};
const bools = new Set(["known_cvd", "pregnant", "symptomatic", "dm", "smoking", "bp_tx", "statin"]);
const choices: Record<string, [string, string][]> = {
  sex: [["female", "女"], ["male", "男"]],
  chol_unit: [["mmol/L", "mmol/L"], ["mg/dL", "mg/dL"]],
  glucose_status: [["unknown", "未确认"], ["normal", "已确认正常"], ["prediabetes", "已确认糖尿病前期"], ["diabetes", "已确诊糖尿病"]],
};
async function post(path: string, body: unknown) {
  const response = await fetch(`/api/prevention/smart-import/${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(Array.isArray(result.detail)
    ? result.detail.map((e: {loc: string[]; msg: string}) => `${e.loc.join(" / ")}: ${e.msg}`).join("；")
    : result.detail || "请求失败，请确认后端已启动");
  return result;
}
function encode(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
}

export function SmartImport({ onApply, disabled }: { onApply: (input: Intake) => void; disabled: boolean }) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<Extraction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [checked, setChecked] = useState(false);
  const [label, setLabel] = useState("导入档案");
  const [source, setSource] = useState<Intake["source"]>("manual");

  function reset() { setResult(null); setChecked(false); setError(""); setNotice(""); }
  async function extract() {
    reset(); setBusy(true);
    try {
      if (file && file.size > 8 * 1024 * 1024) throw new Error("文件最多 8 MB");
      const body = { text, file: file ? { name: file.name, content: await encode(file) } : null };
      setResult(await post("extract", body));
    } catch (e) { setError(e instanceof Error ? e.message : "识别失败"); }
    finally { setBusy(false); }
  }
  function update(index: number | null, key: string, value: Value) {
    if (!result) return;
    setChecked(false);
    setResult({ ...result, draft: index === null ? { ...result.draft, [key]: value }
      : { ...result.draft, visits: result.draft.visits.map((v, i) => i === index ? { ...v, [key]: value } : v) } });
  }
  function field(key: string, value: Value, index: number | null) {
    const path = index === null ? key : `visits.${index}.${key}`;
    const options = bools.has(key) ? [["true", "是（已确认）"], ["false", "否（已确认）"]] : choices[key];
    return <label key={path}>{labels[key]}{value === null && <small> · 待补充</small>}
      {options ? <select value={value === null ? "" : String(value)} onChange={e => update(index, key,
        e.target.value === "" ? null : bools.has(key) ? e.target.value === "true" : e.target.value)}>
        <option value="">未提供 / 待确认</option>{options.map(([v, title]) => <option key={v} value={v}>{title}</option>)}
      </select> : <input type={key === "date" ? "date" : "number"} step="any" value={value === null ? "" : String(value)}
        onChange={e => update(index, key, e.target.value === "" ? null : key === "date" ? e.target.value : Number(e.target.value))} />}
      <small style={{ overflowWrap: "anywhere" }}>原文：{result?.evidence[path] || "未提取到明确依据，请补充核对"}</small>
    </label>;
  }
  async function confirm() {
    if (!result || !checked) return;
    setBusy(true); setError("");
    try {
      const now = new Date();
      const day = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
      const { warnings: _warnings, ...draft } = result.draft;
      void _warnings;
      const response = await post("confirm", { confirmed: true, intake: {
        ...draft, visits: draft.visits.map(v => ({ ...v, glucose_status: v.glucose_status ?? "unknown" })),
        label, source, source_note: `${result.model} 智能导入；${file ? "上传文件" : "粘贴文字"}；已核对原件`, as_of: day,
      } });
      onApply(response.intake); setResult(null);
      setNotice("资料已通过校验并填入下方档案，可点击“评估并生成检查建议”。");
    } catch (e) { setError(e instanceof Error ? e.message : "校验失败"); }
    finally { setBusy(false); }
  }
  return <section className="pv-panel no-print">
    <span className="pv-eyebrow">AI / SMART IMPORT</span><h2>体检资料智能导入</h2>
    <p>上传报告或粘贴文字，AI 整理字段，你只需核对并补充缺项。本地处理，原始文件不保存。</p>
    <fieldset disabled={busy || disabled}>
      <label className="pv-wide">体检文字或补充说明<textarea aria-label="体检文字" rows={5} maxLength={16000}
        style={{ width: "100%", padding: 12, border: "1px solid #cbd5e1", borderRadius: 10 }}
        placeholder="粘贴检查日期、指标、单位及已确认病史；缺少的信息可以稍后补充。"
        value={text} onChange={e => { setText(e.target.value); reset(); }} /></label>
      <label className="pv-wide">选择体检文件<input type="file" accept=".txt,.docx,.pdf,.png,.jpg,.jpeg,.webp"
        onChange={e => { setFile(e.target.files?.[0] ?? null); reset(); }} /></label>
      <p>单文件最多 8 MB；PDF 最多 5 页；Word 仅读取正文和表格文字，内嵌扫描图请转为 PDF。不同患者请分别导入。</p>
      <div className="pv-actions"><button type="button" className="pv-primary" disabled={!text.trim() && !file} onClick={() => void extract()}>
        {busy ? "本地 AI 正在处理，请稍候…" : "AI 提取体检资料"}</button>
        <button type="button" onClick={async () => {
          try { const r = await fetch("/api/prevention/smart-import/status"); const d = await r.json(); setNotice(`${d.model}：${d.message}`); }
          catch { setError("后端未连接"); }
        }}>检查模型状态</button></div>
      {result && <div className="pv-visit"><h3>核对识别结果 · {result.draft.visits.length} 次记录</h3>
        <p>{result.note} 不同单位请核对后填写，修改单位不会自动换算数值。</p>
        {result.draft.warnings.length > 0 && <ul className="pv-alert">{result.draft.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
        <div className="pv-grid"><label>档案代号<input value={label} maxLength={80} onChange={e => { setLabel(e.target.value); setChecked(false); }} /></label>
          <label>资料来源<select value={source} onChange={e => { setSource(e.target.value as Intake["source"]); setChecked(false); }}>
            <option value="manual">用户提供资料</option><option value="synthetic">人工构造示例</option><option value="public_dataset">公开数据集</option></select></label>
          {(["sex", "known_cvd", "pregnant", "symptomatic"] as const).map(k => field(k, result.draft[k], null))}</div>
        {result.draft.visits.map((v, i) => <details className="pv-visit" key={i} open><summary>记录 {i + 1} · {String(v.date ?? "日期待确认")}</summary>
          <div className="pv-grid">{Object.keys(labels).filter(k => !["sex", "known_cvd", "pregnant", "symptomatic"].includes(k)).map(k => field(k, v[k] ?? null, i))}</div></details>)}
        <label><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} /> 我已核对日期、数值、单位和病史，并补充缺失的必填资料</label>
        <div className="pv-actions"><button type="button" disabled={!checked} onClick={() => void confirm()}>确认并填入体检档案</button>
          <button type="button" onClick={reset}>放弃本次识别</button></div>
      </div>}
    </fieldset>
    {error && <p role="alert" className="pv-alert">{error}</p>}
    {notice && <p role="status" className="pv-notice">{notice}</p>}
  </section>;
}
