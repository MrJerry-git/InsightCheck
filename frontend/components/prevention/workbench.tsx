"use client";

import { useEffect, useState } from "react";
import { Activity, ArrowRight, Download, FileCheck2, HeartPulse, Plus, Save, Trash2 } from "lucide-react";
import { example, manual } from "./examples";
import type { Intake, Report, Visit } from "./types";
import "./workbench.css";
import { SmartImport } from "./smart-import";

const fields: [keyof Visit, string, string, number, number, string][] = [
  ["age", "检查时年龄", "岁", 18, 100, "1"],
  ["sbp", "收缩压", "mmHg", 60, 260, "any"],
  ["total_c", "总胆固醇", "按所选单位", 0.1, 600, "any"],
  ["hdl_c", "HDL 胆固醇", "按所选单位", 0.1, 200, "any"],
  ["bmi", "BMI", "kg/m²", 10, 70, "any"],
  ["egfr", "eGFR", "mL/min/1.73m²", 0.1, 200, "any"],
  ["hba1c", "HbA1c（可选）", "%", 3, 20, "any"],
  ["fasting_glucose", "空腹血糖（可选）", "mmol/L", 1, 40, "any"],
];
const booleans: ["dm" | "smoking" | "bp_tx" | "statin", string][] = [
  ["dm", "已有糖尿病病史"], ["smoking", "当前吸烟"],
  ["bp_tx", "使用降压药"], ["statin", "使用他汀"],
];
const outcomeNames: Record<string, string> = {
  total_cvd: "总体心血管疾病", ascvd: "动脉粥样硬化性心血管疾病", heart_failure: "心力衰竭",
};
function download(name: string, content: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a"); a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function api(path: string, body?: Intake) {
  const res = await fetch(`/api/prevention${path}`, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : undefined);
  const data = await res.json();
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(Array.isArray(detail)
      ? detail.map((x: { loc: string[]; msg: string }) => `${x.loc.join(" / ")}: ${x.msg}`).join("；")
      : typeof detail === "string" ? detail : "请求失败，请检查后端服务。");
  }
  return data;
}

export function PreventionWorkbench() {
  const [input, setInput] = useState<Intake | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [history, setHistory] = useState<{ id: string; label: string; source: string; created_at: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => { api("/reports").then(setHistory).catch(() => setNotice("暂未连接后端，请确认服务已启动。")); }, []);
  function change(next: Intake) { setInput(next); setReport(null); setError(""); setNotice(""); }
  function visitChange(index: number, key: keyof Visit, value: unknown) {
    if (input) change({ ...input, visits: input.visits.map((v, i) => i === index ? { ...v, [key]: value } : v) });
  }
  async function run(save = false) {
    if (!input) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api(save ? "/reports" : "/assess", input);
      setReport(result);
      if (save) { setNotice("报告快照已保存到本机数据库。"); setHistory(await api("/reports")); }
    } catch (e) { setError(e instanceof Error ? e.message : "服务连接失败"); }
    finally { setBusy(false); }
  }
  async function load(id: string) {
    setBusy(true); setError(""); setNotice("");
    try { const result = await api(`/reports/${id}`); setInput(result.input); setReport(result); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  async function importFile(file?: File) {
    if (!file) return;
    setBusy(true); setError("");
    try {
      if (file.size > 100000) throw new Error("文件超过 100 KB，请最多导入 20 次结构化记录。");
      const candidate = JSON.parse(await file.text());
      const validated = await api("/assess", candidate);
      setInput(validated.input); setReport(validated); setNotice("结构化资料已通过后端校验。");
    } catch (e) { setError(`导入失败：${e instanceof Error ? e.message : String(e)}`); }
    finally { setBusy(false); }
  }
  return <div className="prevention-workbench">
    <section className="pv-hero">
      <div><span className="pv-eyebrow">INSIGHTCHECK / COMPETITION EDITION</span>
        <h1>把过去的体检，<br />变成下一年的关注重点。</h1>
        <p>体检历史 · 心血管长期风险 · 有依据的检查规划</p>
        <div className="pv-tags"><span>真实方程计算</span><span>规则依据可追溯</span><span>本地研究演示</span></div>
      </div><HeartPulse size={112} strokeWidth={1} aria-hidden="true" />
    </section>
    <div className="pv-steps"><span>01 整理已确认资料</span><ArrowRight size={16} /><span>02 评估长期风险</span><ArrowRight size={16} /><span>03 规划未来一年</span></div>
    <SmartImport onApply={change} disabled={busy} />
    <section className="pv-panel pv-toolbar no-print">
      <div><h2>开始一次规划</h2><p>可使用示例体验，或导入结构化资料。示例不代表真实患者或效果验证。</p></div>
      <div className="pv-actions">
        <button disabled={busy} onClick={() => change(manual())}>新建空白档案</button>
        {(["normal", "prediabetes", "diabetes"] as const).map((kind, i) => <button disabled={busy} key={kind} onClick={() => change(example(kind))}>{["正常随访示例", "前期随访示例", "慢病随访示例"][i]}</button>)}
        <label className="pv-file">导入 JSON<input aria-label="导入结构化体检资料" disabled={busy} type="file" accept=".json" onChange={e => { void importFile(e.target.files?.[0]); e.target.value = ""; }} /></label>
      </div>
      <p>也可选择示例 → 导出资料模板 → 按同样结构填写。AI 导入需先核对，不自动作出诊断。</p>
    </section>
    {error && <div role="alert" className="pv-alert">{error}</div>}
    {notice && <p role="status" className="pv-notice">{notice}</p>}
    {input && <form className="pv-panel no-print" onSubmit={e => { e.preventDefault(); void run(); }}>
      <fieldset disabled={busy}>
        <div className="pv-section-heading"><div><span className="pv-eyebrow">01 / INPUT</span><h2>确认体检档案</h2></div><span className="pv-pill">{input.visits.length} 次记录</span></div>
        <div className="pv-grid">
          <label>档案代号（避免真实姓名）<input required maxLength={80} value={input.label} onChange={e => change({ ...input, label: e.target.value })} /></label>
          <label>模型使用的生理性别<select required value={input.sex} onChange={e => change({ ...input, sex: e.target.value as Intake["sex"] })}><option value="">请选择 / 待确认</option><option value="female">女</option><option value="male">男</option></select></label>
          <label>评估日期<input required type="date" value={input.as_of} onChange={e => change({ ...input, as_of: e.target.value })} /></label>
          <label>资料来源<select value={input.source} onChange={e => change({ ...input, source: e.target.value as Intake["source"] })}><option value="synthetic">人工构造示例</option><option value="manual">手动录入已确认资料</option><option value="public_dataset">公开数据集</option></select></label>
        </div>
        <label className="pv-wide">来源说明<input required maxLength={500} value={input.source_note} onChange={e => change({ ...input, source_note: e.target.value })} /></label>
        <div className="pv-grid pv-visit">{([["known_cvd", "已确诊心血管疾病"], ["pregnant", "当前妊娠"], ["symptomatic", "存在当前不适，需要就医评估"]] as const).map(([key, title]) => <label key={key}>{title}<select required value={input[key] === null ? "" : String(input[key])} onChange={e => change({ ...input, [key]: e.target.value === "" ? null : e.target.value === "true" })}><option value="">请选择 / 待确认</option><option value="false">否（已确认）</option><option value="true">是（已确认）</option></select></label>)}</div>
        {input.visits.map((visit, index) => <details className="pv-visit" key={index} open={index === input.visits.length - 1}>
          <summary>体检记录 {index + 1} · {visit.date || "日期待填写"}（点击展开 / 收起）</summary>
          <div className="pv-section-heading"><h3>体检记录 {index + 1}</h3><button type="button" disabled={input.visits.length === 1} onClick={() => change({ ...input, visits: input.visits.filter((_, i) => i !== index) })}><Trash2 size={14} />删除</button></div>
          <div className="pv-grid"><label>检查日期<input required type="date" value={visit.date} onChange={e => visitChange(index, "date", e.target.value)} /></label>
            <label>胆固醇单位<select value={visit.chol_unit} onChange={e => {
              const unit = e.target.value as Visit["chol_unit"];
              const factor = unit === "mg/dL" ? 1 / 0.02586 : 0.02586;
              change({ ...input, visits: input.visits.map((v, i) => i === index ? { ...v, chol_unit: unit, total_c: v.total_c === null ? null : Number((v.total_c * factor).toFixed(6)), hdl_c: v.hdl_c === null ? null : Number((v.hdl_c * factor).toFixed(6)) } : v) });
            }}><option>mmol/L</option><option>mg/dL</option></select></label>
            {fields.map(([key, title, unit, min, max, step]) => <label key={key}>{title}<span>{unit}</span><input required={key !== "hba1c" && key !== "fasting_glucose"} type="number" min={min} max={max} step={step} value={visit[key] === null || visit[key] === undefined ? "" : String(visit[key])} onChange={e => visitChange(index, key, e.target.value === "" ? null : Number(e.target.value))} /></label>)}
            {booleans.map(([key, title]) => <label key={key}>{title}<select required value={visit[key] === null ? "" : String(visit[key])} onChange={e => visitChange(index, key, e.target.value === "" ? null : e.target.value === "true")}><option value="">请选择 / 待确认</option><option value="false">否（已确认）</option><option value="true">是（已确认）</option></select></label>)}
            <label>既有血糖结论<select value={visit.glucose_status} onChange={e => visitChange(index, "glucose_status", e.target.value)}><option value="unknown">未确认</option><option value="normal">已确认正常</option><option value="prediabetes">已确认糖尿病前期</option><option value="diabetes">已确诊糖尿病</option></select></label>
          </div>
        </details>)}
        <div className="pv-actions"><button type="button" disabled={input.visits.length >= 20} onClick={() => change({ ...input, visits: [...input.visits, { ...input.visits[input.visits.length - 1], date: "" }] })}><Plus size={16} />添加历史记录</button>
          <button type="button" onClick={() => download("insightcheck-intake.json", JSON.stringify(input, null, 2))}><Download size={16} />导出资料模板</button>
          <button className="pv-primary" type="submit"><Activity size={16} />{busy ? "正在处理…" : "评估并生成检查建议"}</button></div>
        <p>新增记录会复制上一条以便填写，请逐项核对；不知道的必填信息应先补齐，不能默认填“否”。</p>
      </fieldset>
    </form>}
    {report && <div className="pv-report" id="competition-report">
      <section className="pv-panel">
        <div className="pv-section-heading"><div><span className="pv-eyebrow">02 / LONG-TERM RISK</span><h2>{report.input.label}</h2><p>评估日期 {report.input.as_of} · {report.input.source === "synthetic" ? "人工示例 / 非真实患者" : "用户提供资料"} · {report.review_status}</p></div><FileCheck2 size={32} /></div>
        {report.blockers.length > 0 && <div className="pv-alert"><strong>本次未生成风险数值</strong><ul>{report.blockers.map(x => <li key={x}>{x}</li>)}</ul><p>不使用默认风险或替代数字；可在上方更正资料后重新计算。</p></div>}
        {report.risk && Object.entries(report.risk.horizons).map(([years, outcomes]) => <div key={years}><h3>未来 {years} 年风险</h3><div className="pv-risk-grid">{Object.entries(outcomes).map(([key, value]) => <article className="pv-risk" key={key}><span>{outcomeNames[key]}</span><strong>{(value * 100).toFixed(2)}<small>%</small></strong><div className="pv-meter"><div style={{ width: `${value * 100}%` }} /></div><p>相似风险因素人群的长期估计</p></article>)}</div></div>)}
        <p>使用 {report.risk?.variant === "hba1c" ? "HbA1c 增强" : "基础"}方程；60 岁及以上不展示 30 年估计。三项风险不可相加，也不代表下一年患病概率。</p>
      </section>
      <section className="pv-panel"><span className="pv-eyebrow">HISTORY / OBSERVED CHANGES</span><h2>既往指标轨迹</h2><div className="pv-trends">{report.trends.filter(t => t.points.length > 0).map(t => {
        const min = Math.min(...t.points.map(p => p.value)); const max = Math.max(...t.points.map(p => p.value));
        return <article key={t.key}><h3>{t.label} <small>{t.unit}</small></h3><svg viewBox="0 0 220 55" role="img" aria-label={`${t.label}历次变化`}><polyline fill="none" stroke="#0f766e" strokeWidth="2.5" points={t.points.map((p, i) => `${10 + i * 200 / Math.max(1, t.points.length - 1)},${45 - (p.value - min) / (max - min || 1) * 35}`).join(" ")} />{t.points.map((p, i) => <circle key={p.date} cx={10 + i * 200 / Math.max(1, t.points.length - 1)} cy={45 - (p.value - min) / (max - min || 1) * 35} r="3" fill="#0f766e" />)}</svg><p>{t.points.map(p => `${p.date}: ${p.value}`).join(" → ")}</p><b>{t.change === null ? "仅一次测量，不判断趋势" : `首末变化 ${t.change > 0 ? "+" : ""}${t.change}`}</b></article>;
      })}</div><p>仅描述测量变化；图形纵轴按各指标自身范围缩放，不表示疾病严重程度。</p></section>
      <section className="pv-panel"><span className="pv-eyebrow">03 / NEXT-YEAR PLAN</span><h2>未来一年，重点关注什么？</h2><p>规划窗口 {report.planning_window.join(" 至 ")}。以下是待审核建议，不是已确认医疗方案。</p>
        <div className="pv-plan">{report.recommendations.map(item => <article key={item.code}><div><h3>{item.title}</h3><span className="pv-pill">{item.decision}</span></div><p>{item.reason}</p><p><b>{item.due_date ? `建议安排/讨论日期：${item.due_date}` : "具体时间由医生结合实际情况确认"}</b></p><small>{item.basis} · <a href={report.sources[item.source].url} target="_blank" rel="noreferrer">{report.sources[item.source].title} ↗</a></small></article>)}</div>
      </section>
      <section className="pv-panel"><h2>依据与使用范围</h2><ul>{report.limitations.map(x => <li key={x}>{x}</li>)}</ul><p>来源：{report.input.source_note}</p><p>计算实现 {report.risk?.version ?? "未计算"} · 规则 {report.rules_version}<br />上游版本 {report.upstream}</p><p>PREVENT equations: Khan et al., Circulation 2023. DOI: 10.1161/CIRCULATIONAHA.123.067626. 本平台不是 AHA 官方产品，也未获得其背书。第三方 preventr 实现采用 MIT 许可。</p>
        <div className="pv-actions no-print"><button disabled={busy || !!report.id} onClick={() => void run(true)}><Save size={16} />{report.id ? "快照已保存" : "保存报告快照"}</button><button onClick={() => download("insightcheck-report.json", JSON.stringify(report, null, 2))}><Download size={16} />导出完整报告 JSON</button><button onClick={() => window.print()}>打印 / 保存 PDF</button></div>
      </section>
    </div>}
    <section className="pv-panel no-print"><h2>已保存的规划报告</h2><p>保存在当前后端数据库中；本地比赛版没有账号隔离，请只使用脱敏或示例资料。</p>{history.length ? <div className="pv-history">{history.map(row => <button disabled={busy} onClick={() => void load(row.id)} key={row.id}><span>{row.label}</span><small>{row.source === "synthetic" ? "人工示例" : "录入资料"} · {row.created_at.slice(0, 10)}</small><ArrowRight size={16} /></button>)}</div> : <p>暂无保存记录。完成评估后可保存并回看。</p>}</section>
  </div>;
}
