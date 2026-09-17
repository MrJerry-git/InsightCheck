"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { request } from "@/services/api-client";
import { Button } from "@/components/ui/button";
import { appConfig } from "@/lib/config";

type Patient = { id: string; code: string; checks: number; gender: string; birth_date: string | null };
type Metric = { id: string; code: string; name: string; value: number | null; unit: string; date: string };
type Check = { id: string; date: string; is_demo: boolean; metrics: Metric[]; images: { id: string; date: string; report: string; lesions: { id: string; location: string; size_mm: number | null }[] }[] };
type History = { code: string; source_kind: string; checks: Check[]; trends: Record<string, Metric[]>; availability: string; tracks: { id: string; location: string; observations: { date: string; size_mm: number | null; status: string }[] }[] };
type Plan = { id: string; summary: string; source_kind: string; status: string; version: string; explanation: string; explanation_provider: string; history: History; risk: { probability: number | null; status: string }; items: { id: string; name: string; group: string; reason: string; rule_status: string; score: number | null; rank: number; cost: string; rules: { execution_trace: { rule_code: string; reason: string; matched: boolean }[] } }[] };
type Saved = { id: string; created_at: string; summary: string };
type Dictionary = { metric_code: string; canonical_name: string; standard_unit: string };
const input = "rounded-md border bg-background p-2 text-sm min-w-0";
const panel = "rounded-xl border bg-card p-5 space-y-4";
const titles: Record<string, string> = { dashboard: "完整流程工作台", patients: "受检者档案", trends: "纵向指标趋势", imaging: "影像与病灶记录", "risk-analysis": "风险与项目分析", recommendations: "方案生成与历史", "ai-report": "方案报告", "ai-chat": "方案说明助手" };

export function Workbench({ mode = "dashboard", initialPatient = "", planId = "" }: { mode?: string; initialPatient?: string; planId?: string }) {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [selected, setSelected] = useState(initialPatient);
  const [cutoff, setCutoff] = useState(() => new Date().toLocaleDateString("en-CA"));
  const [history, setHistory] = useState<History | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [saved, setSaved] = useState<Saved[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [code, setCode] = useState("");
  const [birth, setBirth] = useState("");
  const [gender, setGender] = useState("unknown");
  const [dictionary, setDictionary] = useState<Dictionary[]>([]);
  const [metricCode, setMetricCode] = useState("");
  const [metricValue, setMetricValue] = useState("");
  const [demoRecord, setDemoRecord] = useState(false);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "操作失败"); }
    finally { setBusy(false); }
  }
  async function refresh() {
    const [p, d] = await Promise.all([request<Patient[]>("/workflow/patients"), request<Dictionary[]>("/metric-dictionaries?limit=500")]);
    setPatients(p); setDictionary(d);
  }
  useEffect(() => {
    let active = true;
    Promise.all([request<Patient[]>("/workflow/patients"), request<Dictionary[]>("/metric-dictionaries?limit=500")])
      .then(([p, d]) => { if (active) { setPatients(p); setDictionary(d); } })
      .catch(e => { if (active) setError(String(e)); });
    if (planId) request<Plan>(`/workflow/plans/${encodeURIComponent(planId)}`).then(p => { if (active) setPlan(p); }).catch(e => { if (active) setError(String(e)); });
    return () => { active = false; };
  }, [planId]);
  async function load(id = selected) {
    const [h, s] = await Promise.all([request<History>(`/workflow/patients/${encodeURIComponent(id)}?as_of_date=${cutoff}`), request<Saved[]>(`/workflow/plans?patient_id=${encodeURIComponent(id)}`)]);
    setHistory(h); setSaved(s);
  }
  const showHistory = ["dashboard", "patients", "trends", "imaging"].includes(mode);
  return <div className="space-y-6" aria-busy={busy}>
    <header className="space-y-2"><p className="text-sm text-primary">InsightCheck · 1.0 工程预览</p><h1 className="text-3xl font-bold">{titles[mode] || "方案详情"}</h1><p className="text-muted-foreground">建立档案 → 查看历史 → 分析与排序 → 规则检查 → 保存方案</p></header>
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">合成模型仅演示完整流程；非合成资料不输出模拟概率。方案均为草稿，未完成医学有效性验证。</div>
    {error && <p role="alert" className="rounded-lg border border-destructive p-3 text-destructive">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {busy && <p role="status">正在处理，请稍候…</p>}
    <section className={panel}>
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-sm">受检者<select aria-label="受检者" className={input} disabled={busy} value={selected} onChange={e => { setSelected(e.target.value); setHistory(null); setPlan(null); setSaved([]); setAnswer(""); }}><option value="">请选择档案</option>{patients.map(p => <option key={p.id} value={p.id}>{p.code} · {p.checks} 次记录</option>)}</select></label>
        <label className="grid gap-1 text-sm">分析截止日期<input className={input} type="date" value={cutoff} disabled={busy} onChange={e => { setCutoff(e.target.value); setHistory(null); setPlan(null); }} /></label>
        <Button disabled={busy || !selected || !cutoff} onClick={() => void act(() => load())}>加载档案</Button>
        <Button variant="outline" disabled={busy} onClick={() => void act(async () => { const p = await request<{patient_id: string}>("/workflow/demo", {method: "POST"}); await refresh(); setSelected(p.patient_id); setPlan(null); await load(p.patient_id); setNotice("已加载合成演示案例，可继续生成方案。"); })}>创建 / 加载演示案例</Button>
        <Link className="text-sm text-primary underline" href="/health-records">批量导入历史记录</Link>
      </div>
      <p className="text-sm text-muted-foreground">{patients.length} 份档案。可直接加载演示案例，无需上传资料。</p>
    </section>
    {["dashboard", "patients"].includes(mode) && <section className={panel}><h2 className="text-xl font-semibold">建立档案</h2><form className="flex flex-wrap gap-3" onSubmit={e => { e.preventDefault(); void act(async () => { const p = await request<{id: string}>("/patients", {method: "POST", body: JSON.stringify({anonymous_code: code, birth_date: birth || null, gender})}); await refresh(); setSelected(p.id); setHistory(null); setPlan(null); setSaved([]); setNotice("档案已创建，可以录入记录。"); }); }}>
      <input aria-label="匿名编号" placeholder="匿名编号" required maxLength={64} className={input} value={code} onChange={e => setCode(e.target.value)} />
      <label className="text-sm">出生日期 <input aria-label="出生日期" type="date" className={input} value={birth} onChange={e => setBirth(e.target.value)} /></label>
      <select aria-label="性别" className={input} value={gender} onChange={e => setGender(e.target.value)}><option value="unknown">性别未知</option><option value="female">女</option><option value="male">男</option><option value="other">其他</option></select>
      <Button type="submit" disabled={busy || !code.trim()}>保存档案</Button>
    </form>
    <h2 className="text-xl font-semibold">录入单次指标</h2><p className="text-sm text-muted-foreground">记录日期使用上方截止日期，数值按字典标准单位填写。</p>
    <form className="flex flex-wrap items-center gap-3" onSubmit={e => { e.preventDefault(); void act(async () => { await request("/workflow/records", {method: "POST", body: JSON.stringify({patient_id: selected, check_date: cutoff, is_demo: demoRecord, metrics: [{code: metricCode, value: Number(metricValue)}]})}); await refresh(); await load(); setPlan(null); setNotice("记录已保存。"); }); }}>
      <select aria-label="指标" required className={input} value={metricCode} onChange={e => setMetricCode(e.target.value)}><option value="">选择指标与单位</option>{dictionary.map(d => <option key={d.metric_code} value={d.metric_code}>{d.canonical_name} ({d.standard_unit})</option>)}</select>
      <input aria-label="指标数值" className={input} required type="number" step="any" value={metricValue} onChange={e => setMetricValue(e.target.value)} placeholder="数值" />
      <label className="text-sm"><input type="checkbox" checked={demoRecord} onChange={e => setDemoRecord(e.target.checked)} /> 明确为合成记录</label><Button type="submit" disabled={busy || !selected || !cutoff}>保存记录</Button>
    </form></section>}
    {history && showHistory && <section className={panel}><h2 className="text-xl font-semibold">{history.code} · {history.checks.length} 次记录</h2><p className="text-sm">{history.source_kind === "synthetic" ? "合成数据" : "来源待核验"} · {history.availability}</p>
      {Object.entries(history.trends).map(([key, values]) => <div key={key} className="rounded-lg border p-3"><h3 className="font-medium">{values[0].name} · {values[0].unit}</h3><div className="flex flex-wrap gap-4 py-3">{values.map(v => <div key={v.id} className="min-w-24 border-l-2 border-primary pl-3"><p className="text-xs text-muted-foreground">{v.date}</p><p className="text-xl font-semibold">{v.value ?? "缺失"}</p></div>)}</div><p className="text-xs text-muted-foreground">按时间展示原始标准化数值，数值变化不直接解释为疾病进展。</p></div>)}
      {history.checks.length === 0 && <p>截止日期之前没有记录。</p>}
      <h3 className="font-semibold">影像与病灶</h3>{history.checks.flatMap(c => c.images).length === 0 && <p className="text-sm">暂无结构化影像资料，不代表未发现病灶。</p>}
      {history.checks.flatMap(c => c.images).map(i => <div key={i.id} className="border-l-2 pl-3"><p>{i.date} · {i.report}</p>{i.lesions.map(l => <p key={l.id}>{l.location} · {l.size_mm ?? "大小未知"} mm</p>)}</div>)}
      {history.tracks.map(t => <div key={t.id}><p className="font-medium">已记录的病灶轨迹 · {t.location}</p><p className="text-sm">{t.observations.map(o => `${o.date}: ${o.size_mm ?? "未知"} mm (${o.status})`).join(" → ")}</p></div>)}
    </section>}
    <section className={panel}><h2 className="text-xl font-semibold">生成并保存方案草稿</h2><p className="text-sm text-muted-foreground">按截止日期计算并保存输入快照、模型状态、排序与规则记录。当前输出统一草稿，费用与档位差异待配置。</p>
      <Button disabled={busy || !selected || !cutoff} onClick={() => void act(async () => { const p = await request<Plan>("/workflow/plans", {method: "POST", body: JSON.stringify({request_id: crypto.randomUUID(), patient_id: selected, as_of_date: cutoff, tier: "standard"})}); setPlan(p); setAnswer(""); await load(); setNotice("方案已保存，可以回看或导出。"); })}>运行分析并保存方案</Button>
      <div className="space-y-2">{saved.map(s => <div key={s.id} className="flex flex-wrap gap-3 text-sm"><button className="text-primary underline" disabled={busy} onClick={() => void act(async () => { setPlan(await request<Plan>(`/workflow/plans/${s.id}`)); setAnswer(""); })}>{s.summary}</button><Link href={`/recommendations/${s.id}`}>独立详情 ↗</Link><span className="text-muted-foreground">{s.created_at}</span></div>)}</div>
    </section>
    {plan && <section className={panel}><div className="flex flex-wrap justify-between gap-3"><h2 className="text-xl font-semibold">已保存方案 · 草稿</h2><a className="rounded-lg border px-4 py-2 text-sm" href={`${appConfig.apiBaseUrl}/workflow/plans/${encodeURIComponent(plan.id)}/export`}>导出方案与证据</a></div>
      <p>{plan.summary}</p><p className="text-sm text-muted-foreground">编号 {plan.id} · {plan.version} · {plan.source_kind}</p>
      <div className="rounded-lg bg-muted p-4"><p className="font-semibold">风险模块：{plan.risk.probability === null ? "未评估" : `${(plan.risk.probability * 100).toFixed(1)}%（合成任务）`}</p><p className="text-sm">{plan.risk.status}</p></div>
      <p className="text-sm">必要项目：尚无已审核依据。候选排序分数不是医学必要性概率。</p>
      {plan.items.map(i => <article key={i.id} className="rounded-lg border p-4"><div className="flex flex-wrap justify-between"><h3 className="font-semibold">{i.rank}. {i.name}</h3><span>{i.group}</span></div><p className="text-sm">匹配分数 {i.score?.toFixed(3) ?? "未计算"} · 规则 {i.rule_status} · 费用 {i.cost}</p><p className="text-sm text-muted-foreground">{i.reason}</p>{i.rules.execution_trace.map((r, n) => <p className="text-xs" key={n}>{r.rule_code} · {r.matched ? "命中" : "未命中"} · {r.reason}</p>)}</article>)}
      <h3 className="font-semibold">方案解释</h3><p>{plan.explanation}</p><p className="text-xs text-muted-foreground">{plan.explanation_provider}</p>
      <form className="flex gap-2" onSubmit={e => { e.preventDefault(); void act(async () => { const a = await request<{answer: string; provider: string}>(`/workflow/plans/${plan.id}/explain`, {method: "POST", body: JSON.stringify({text: question})}); setAnswer(`${a.answer}（${a.provider}）`); }); }}><input aria-label="方案问题" className={`${input} flex-1`} required maxLength={1000} placeholder="询问此方案的风险、费用或数据来源" value={question} onChange={e => setQuestion(e.target.value)} /><Button type="submit" disabled={busy}>查看说明</Button></form>{answer && <p role="status" className="rounded-lg bg-muted p-3">{answer}</p>}
    </section>}
  </div>;
}
