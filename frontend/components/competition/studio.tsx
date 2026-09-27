"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { ArrowDownToLine, ArrowLeft, ArrowRight, Check, ChevronRight, CircleHelp, FileText, HeartPulse, History, LoaderCircle, Paperclip, Plus, RefreshCw, Send, ShieldCheck, Sparkles, X } from "lucide-react";
import type { Intake, Report } from "../prevention/types";
import { api, coverage, display, labels, recommendations, systems, today, localDate, units, type SystemKey } from "./domain";
import { Body, Doctor, Organ } from "./illustrations";
import "./studio.css";

type Row = Record<string, string | number | boolean | null>;
type Extraction = { draft: Row & { visits: Row[]; warnings: string[] }; missing: string[]; model: string };
type Saved = { id: string; label: string; source: string; created_at: string };
const storageKey = "insightcheck-competition-report-v2";
const keys = Object.keys(systems) as SystemKey[];

function readReport(): Report | null {
  try { const raw = sessionStorage.getItem(storageKey); if (!raw) return null; const r = JSON.parse(raw); return r?.input?.visits?.length && Array.isArray(r.recommendations) && Array.isArray(r.trends) ? r : null; } catch { return null; }
}
function encode(file: File): Promise<string> { return new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result).split(",")[1]); r.onerror = () => reject(new Error("文件读取失败，请重新选择。")); r.readAsDataURL(file); }); }

export function CompetitionStudio({ page }: { page: string }) {
  const router = useRouter();
  const [report, setReport] = useState<Report | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [transition, setTransition] = useState<SystemKey | null>(null);
  const [origin, setOrigin] = useState({ x: 0, y: 0, scale: 0.25 });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [saved, setSaved] = useState<Saved[]>([]);
  const [archive, setArchive] = useState(false);
  const [archiveError, setArchiveError] = useState("");
  const plan = page.startsWith("plan/");
  const system = page.split("/")[1] as SystemKey | "all" | undefined;
  const isHome = page === "";
  useEffect(() => { const t = setTimeout(() => { setReport(readReport()); setReady(true); }, 0); return () => { clearTimeout(t); if (timer.current) clearTimeout(timer.current); }; }, []);
  function accept(next: Report) {
    setReport(next);
    try { sessionStorage.setItem(storageKey, JSON.stringify(next)); } catch { setNotice("浏览器无法保存当前会话，请在整体规划页保存报告后再离开。"); }
  }
  function go(path: string, key?: SystemKey) {
    if (transition) return;
    setError("");
    if (key) { const rect = document.querySelector(isHome ? `.cs-body-target.${key}, .label-${key}` : ".cs-organ-link .cs-organ")?.getBoundingClientRect(); if (rect) setOrigin({ x: rect.left + rect.width / 2 - window.innerWidth / 2, y: rect.top + rect.height / 2 - window.innerHeight / 2, scale: rect.width / 300 }); setTransition(key); timer.current = setTimeout(() => { router.push(`/competition/${path}`); setTransition(null); }, 420); }
    else router.push(path ? `/competition/${path}` : "/competition");
  }
  async function showArchive() { setArchive(true); setArchiveError(""); try { setSaved(await api<Saved[]>("/reports")); } catch (e) { setArchiveError((e as Error).message); } }
  async function load(id: string) { setBusy(true); setArchiveError(""); try { accept(await api<Report>(`/reports/${id}`)); setArchive(false); } catch (e) { setArchiveError((e as Error).message); } finally { setBusy(false); } }
  async function save() { if (!report) return; setBusy(true); setError(""); try { accept(await api<Report>("/reports", report.input)); setNotice("这份规划已保存，可在“已保存规划”中回看。"); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  const lit = Object.fromEntries(keys.map(k => [k, coverage(report, k)])) as Record<SystemKey, boolean>;
  const visitCount = report?.input.visits.length ?? 0;
  return <div className="cs-app">
    <header className="cs-header no-print"><button className="cs-brand" onClick={() => go("")} aria-label="循影定检，返回人体总览"><span><HeartPulse size={23}/></span><b>循影定检<small>INSIGHTCHECK</small></b></button>
      <nav aria-label="参赛版导航"><button className={isHome ? "active" : ""} onClick={() => go("")}>健康地图</button><button className={plan && system === "all" ? "active" : ""} onClick={() => go("plan/all")}>下一年规划</button></nav>
      <span className="cs-private"><ShieldCheck size={15}/>本地研究版</span>
    </header>
    <main className={`cs-main ${isHome ? "home" : "detail"}`}>
      {!isHome && <button className="cs-back no-print" onClick={() => go(plan && system !== "all" ? `system/${system}` : "")}><ArrowLeft size={15}/>{plan && system !== "all" ? "返回体检历史" : "返回健康地图"}</button>}
      <div className="cs-page-title"><div><span className="cs-eyebrow">{isHome ? "YOUR HEALTH, CONNECTED" : plan ? "A THOUGHTFUL PLAN FOR YOU" : "A CLOSER LOOK AT YOUR HEALTH"}</span><h1>{isHome ? <>让每一份体检，<em>连接下一年的健康。</em></> : system === "all" ? "你的下一年检查规划" : `${systems[system!].name}${plan ? " · 检查规划" : ""}`}</h1><p>{isHome ? "整理过去的体检记录，从身体地图出发，找到值得关注的下一步。" : plan ? "把已有资料转化为有依据的安排。每一项建议，都有它的原因。" : systems[system as SystemKey].description}</p></div><div className="cs-date"><span>HEALTH JOURNAL</span><b>{report?.input.as_of ?? today()}</b></div></div>
      {error && <div className="cs-alert" role="alert">{error}</div>}{notice && <div className="cs-notice" role="status">{notice}<button aria-label="关闭提示" onClick={() => setNotice("")}><X size={14}/></button></div>}
      {report?.input.source === "synthetic" && <p className="cs-warning">当前为人工构造示例，不是真实患者或效果验证。</p>}
      {!ready ? <div className="cs-empty"><LoaderCircle className="spin"/>正在整理当前会话…</div> : isHome ? <>
        <div className="cs-home-grid">
          <section className="cs-map-panel"><div className="cs-panel-title"><div><span className="cs-eyebrow">01 / BODY MAP</span><h2>你的健康地图</h2></div><span className="cs-soft-tag">{keys.filter(k => lit[k]).length} / 3 已点亮</span></div>
            <div className="cs-map-stage"><div className="cs-map-lines"/><Body lit={lit} onSelect={k => go(`system/${k}`, k)}/><div className="cs-system-labels">{keys.map((k, i) => <button key={k} className={`cs-system-label label-${k} ${lit[k] ? "lit" : ""}`} disabled={!lit[k]} onClick={() => go(`system/${k}`, k)}><span className="cs-label-number">0{i + 1}</span><span><b>{systems[k].short}</b><small>{lit[k] ? "资料已确认 · 查看详情" : "等待相关资料"}</small></span><ChevronRight size={14}/></button>)}</div></div>
            <div className="cs-map-legend"><span><i/>尚无资料</span><span><i className="lit"/>已确认资料</span><span>点亮不表示健康或疾病状态</span></div>
          </section>
          <ImportPanel report={report} onAccept={accept}/>
        </div>
        <div className="cs-home-bottom"><div><span className="cs-small-icon"><History size={21}/></span><div><b>{visitCount ? `${visitCount} 次体检，连接成一条时间线` : "从一份报告，开始了解自己"}</b><p>{visitCount ? "点击点亮的部位，回看相关指标与历史变化。" : "确认资料后，相关部位会被点亮。无需一次准备好所有报告。"}</p></div></div><button className="cs-primary" onClick={() => go("plan/all")}>查看整体检查规划<ArrowRight size={17}/></button></div>
      </> : !report ? <div className="cs-empty"><FileText size={38}/><h2>先为规划准备一份资料</h2><p>上传并确认体检资料后，即可查看历史和检查建议。</p><button className="cs-primary" onClick={() => go("")}>去导入资料<ArrowRight size={16}/></button>{system === "all" && <button className="cs-text-button" onClick={() => void showArchive()}>查看已保存规划</button>}</div> : plan ? <Plan report={report} scope={system!} go={go} busy={busy} save={save} showArchive={showArchive}/> : <SystemDetail report={report} system={system as SystemKey} go={go}/>}
      <footer className="cs-footer"><span>循影定检 · 让检查更有依据</span><p>研究演示，不用于诊断或治疗。风险为长期估计，检查建议需经医学审核。</p></footer>
    </main>
    {transition && <div className="cs-transition" aria-hidden="true" style={{ "--origin-x": `${origin.x}px`, "--origin-y": `${origin.y}px`, "--origin-scale": origin.scale } as CSSProperties}><Organ kind={transition}/></div>}
    {archive && <div className="cs-modal-scrim" onClick={() => setArchive(false)}><section className="cs-archive" role="dialog" aria-modal="true" aria-label="已保存规划" onClick={e => e.stopPropagation()} onKeyDown={e => { if (e.key === "Escape") setArchive(false); if (e.key === "Tab") { const buttons = e.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"); const first = buttons[0]; const last = buttons[buttons.length - 1]; if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); } } }}><div className="cs-panel-title"><h2>已保存规划</h2><button autoFocus aria-label="关闭已保存规划" onClick={() => setArchive(false)}><X/></button></div><p>本机报告快照保留当时的资料与评估日期。</p>{archiveError && <p role="alert">{archiveError}</p>}{!saved.length && !archiveError && <p>暂无已保存规划。</p>}{saved.map(r => <button className="cs-archive-row" disabled={busy} onClick={() => void load(r.id)} key={r.id}><FileText size={19}/><span><b>{r.label}</b><small>{localDate(r.created_at)} · {r.source === "synthetic" ? "人工示例" : "已保存资料"}</small></span><ArrowRight size={17}/></button>)}</section></div>}
  </div>;
}

function ImportPanel({ report, onAccept }: { report: Report | null; onAccept: (r: Report) => void }) {
  const [message, setMessage] = useState("");
  const [context, setContext] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [draft, setDraft] = useState<Extraction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("正在检查本地 AI");
  const [modelReady, setModelReady] = useState(false);
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  async function checkStatus() { try { const s = await api<{ ready: boolean; message: string }>("/smart-import/status"); setModelReady(s.ready); setStatus(s.ready ? "本地 AI 已就绪" : "本地 AI 未启动，请启动智能导入服务"); } catch { setModelReady(false); setStatus("未连接到本地服务"); } }
  useEffect(() => { const task = setTimeout(() => { void checkStatus(); }, 0); return () => clearTimeout(task); }, []);
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [messages, busy]);
  async function extract(retry = false) {
    if (busy) return;
    if (!retry && message.length < 200 && /删除|撤销|修改|改成|改为|更正/.test(message)) { setMessages(m => [...m, {role: "user", text: message}, {role: "assistant", text: "逐条修改、删除和撤销暂未开放，这条消息没有更改任何记录。请准备完整的更正资料重新识别，或等对话管理功能接入后再操作。"}]); setMessage(""); return; }
    const text = retry ? context : [context, message.trim()].filter(Boolean).join("\n补充说明：\n");
    if (!text && !file) return;
    if (text.length > 16000) { setError("本轮文字已超过 16000 字，请精简资料后重新开始。"); return; }
    setBusy(true); setError(""); setDraft(null);
    if (!retry) { setMessages(m => [...m, { role: "user", text: message.trim() || `请整理这份报告：${file?.name}` }]); setMessage(""); setContext(text); }
    try {
      const result = await api<Extraction>("/smart-import/extract", { text, file: file ? { name: file.name, content: await encode(file) } : null });
      setDraft(result);
      const missing = result.missing.map(p => { const parts = p.split("."); return parts[0] === "visits" ? `第 ${Number(parts[1]) + 1} 次记录的${labels[parts[2]] ?? "资料"}` : labels[p] ?? "资料"; });
      setMessages(m => [...m, { role: "assistant", text: missing.length ? `整理了 ${result.draft.visits.length} 次记录。还需要你补充：${missing.join("、")}。请在下方说明；不确定的信息不要猜测。` : `整理了 ${result.draft.visits.length} 次记录，请核对下方的信息摘要。确认无误后，点击“确认资料并点亮”。` }]);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function confirm() {
    if (!draft) return; setBusy(true); setError("");
    try {
      const { warnings: _warnings, ...data } = draft.draft; void _warnings;
      const response = await api<{ intake: Intake }>("/smart-import/confirm", { confirmed: true, intake: { ...data, visits: data.visits.map(v => ({ ...v, glucose_status: v.glucose_status ?? "unknown" })), label: `体检档案 · ${today()}`, source: "manual", source_note: "智能导入，已由用户核对确认", as_of: today() } });
      onAccept(await api<Report>("/assess", response.intake)); setDraft(null); setContext(""); setFile(null);
      setMessages(m => [...m, { role: "assistant", text: "资料已确认，相关部位已点亮。你可以查看体检历史，也可以直接查看整体检查规划。请在规划页保存报告，以便今后回看。" }]);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  function selectFile(next?: File) {
    if (!next) return;
    if (next.size > 8 * 1024 * 1024) { setError("单份文件不能超过 8 MB。"); return; }
    if (!/\.(pdf|docx|txt|png|jpe?g|webp)$/i.test(next.name)) { setError("请上传 PDF、Word、文字或清晰图片。"); return; }
    setFile(next); setDraft(null); setContext(""); setError(""); setMessage(""); setMessages([]);
  }
  return <section className="cs-import"><div className="cs-panel-title"><div className="cs-assistant-title"><span><Sparkles size={21}/></span><div><h2>体检资料助手</h2><p><i className={modelReady ? "ready" : ""}/>{status}</p></div></div><button title="重新检查服务" aria-label="重新检查 AI 服务" onClick={() => void checkStatus()}><RefreshCw size={16}/></button></div>
    <div className="cs-conversation" ref={scrollRef} aria-live="polite"><div className="cs-chat-intro"><span className="cs-eyebrow">LET’S START WITH YOUR STORY</span><h3>把报告交给我，<br/>让信息变得清晰。</h3><p>上传体检报告，或粘贴其中的文字。<br/>我会整理指标，与你一起核对缺失的信息。</p></div>
      {report && !draft && <details className="cs-extracted"><summary>已确认资料 · {report.input.visits.length} 次体检（展开核对）</summary><dl>{["sex", "known_cvd", "pregnant", "symptomatic"].map(k => <div key={k}><dt>{labels[k]}</dt><dd>{display(report.input[k as keyof Intake])}</dd></div>)}</dl>{report.input.visits.map(v => <div key={v.date}><b>{v.date}</b><dl>{Object.entries(v).filter(([k]) => k !== "date").map(([k,value]) => <div key={k}><dt>{labels[k]}</dt><dd>{display(value)} {units[k] ?? ""}</dd></div>)}</dl></div>)}</details>}
      {!messages.length && <button className="cs-upload" disabled={busy} onClick={() => inputRef.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!busy) selectFile(e.dataTransfer.files[0]); }}><span><Plus size={24}/></span><b>选择或拖入体检报告</b><small>PDF、Word、图片、文字 · 单份不超过 8 MB</small></button>}
      {messages.map((m, i) => <div className={`cs-message ${m.role}`} key={i}>{m.role === "assistant" && <Sparkles size={15}/>}<p>{m.text}</p></div>)}
      {busy && <div className="cs-message assistant"><LoaderCircle className="spin" size={16}/><p>正在本地处理，请稍候…</p></div>}
      {draft && <section className="cs-extracted"><div className="cs-panel-title"><b>待核对的信息</b><span className="cs-soft-tag">尚未点亮</span></div><dl>{["sex", "known_cvd", "pregnant", "symptomatic"].map(k => <div key={k}><dt>{labels[k]}</dt><dd>{display(draft.draft[k])}</dd></div>)}</dl>{draft.draft.visits.map((v, i) => <details key={i} open><summary>记录 {i + 1} · {display(v.date)}</summary><dl>{Object.entries(v).filter(([k]) => k !== "date").map(([k, value]) => <div key={k}><dt>{labels[k] ?? k}</dt><dd>{display(value)}{value !== null ? ` ${["total_c", "hdl_c"].includes(k) ? (v.chol_unit ?? "") : units[k] ?? ""}` : ""}</dd></div>)}</dl></details>)}{draft.draft.warnings.length > 0 && <p className="cs-warning">有 {draft.draft.warnings.length} 项资料需要进一步核对，请确认日期、单位、病史及未填写的信息。</p>}<button className="cs-primary" disabled={busy || draft.missing.length > 0 || !!message.trim()} onClick={() => void confirm()}><Check size={16}/>确认资料并点亮</button><p className="cs-fine">{report ? "确认后将替换本次工作档案；已保存报告不受影响。" : "请核对日期、数值、单位与病史后确认。"}</p></section>}
    </div>
    <div className="cs-composer"><input ref={inputRef} type="file" hidden aria-label="选择体检报告" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.webp" onChange={e => { selectFile(e.target.files?.[0]); e.target.value = ""; }}/>{file && <div className="cs-file-chip"><FileText size={15}/><span>{file.name}</span><button disabled={busy} aria-label="移除待上传文件" onClick={() => { setFile(null); setDraft(null); setContext(""); }}><X size={14}/></button></div>}{error && <div role="alert" className="cs-import-error">{error}<button disabled={busy} onClick={() => void extract(true)}>重试</button></div>}
      <form onSubmit={e => { e.preventDefault(); void extract(); }}><textarea aria-label="与体检资料助手交流" placeholder={draft ? "补充缺少的信息，例如：检查日期是…" : "粘贴报告文字，开始整理…"} rows={2} maxLength={16000} value={message} disabled={busy} onChange={e => setMessage(e.target.value)}/><div><button type="button" disabled={busy} aria-label="添加报告附件" onClick={() => inputRef.current?.click()}><Paperclip size={19}/></button><span>资料仅在本地处理</span><button className="cs-send" type="submit" disabled={busy || (!message.trim() && !file)} aria-label="发送资料或补充信息">{busy ? <LoaderCircle size={17} className="spin"/> : <Send size={17}/>}</button></div></form>
      <button type="button" className="cs-text-button" disabled={busy} onClick={() => { setMessage(""); setContext(""); setFile(null); setDraft(null); setError(""); setMessages([]); }}>重新开始整理（保留已确认资料）</button>
      <details className="cs-capability"><summary><CircleHelp size={12}/>当前可用能力</summary><p>支持报告识别、补充说明后重新提取及确认。逐条修改、删除、撤销和跨次合并尚待对话服务接入；目前请在同一轮资料中提供需要评估的历年记录。不要在此提交删除指令。PDF 最多 5 页，Word 仅读取文字。</p></details>
    </div>
  </section>;
}

function SystemDetail({ report, system, go }: { report: Report; system: SystemKey; go: (path: string, k?: SystemKey) => void }) {
  const spec = systems[system];
  const visits = [...report.input.visits].sort((a, b) => a.date.localeCompare(b.date));
  const latest = visits.at(-1)!;
  const metrics = spec.metrics.map(key => { const points = visits.filter(v => v[key as keyof typeof v] !== null).map(v => ({ date: v.date, value: Number(v[key as keyof typeof v]) })); return { key, points }; });
  return <div className="cs-detail-grid"><aside className="cs-organ-card"><span className="cs-eyebrow">{spec.english}</span><button className="cs-organ-link" onClick={() => go(`plan/${system}`, system)} aria-label={`查看${spec.name}检查规划`}><Organ kind={system}/><span>从了解，到下一步<ArrowRight size={17}/></span></button><h2>{spec.name}</h2><p>{system === "heart" ? "历史指标 · 长期风险 · 检查建议" : "历史指标 · 有依据的随访建议"}</p><span className="cs-confirmed"><Check size={13}/>{coverage(report, system) ? "相关资料已确认" : "尚无该项指标"}</span><button className="cs-primary no-print" onClick={() => go(`plan/${system}`, system)}>查看检查规划<ArrowRight size={16}/></button><button className="cs-text-button no-print" onClick={() => go("")}>返回助手补充资料</button></aside>
    <div className="cs-detail-content"><section className="cs-card"><div className="cs-panel-title"><div><span className="cs-eyebrow">YOUR HISTORY</span><h2>每一次记录，都值得连接</h2></div><span className="cs-soft-tag">{visits.length} 次体检</span></div><div className="cs-metrics">{metrics.map(({ key, points }) => { const value = latest[key as keyof typeof latest]; const min = Math.min(...points.map(p => p.value)); const max = Math.max(...points.map(p => p.value)); return <article key={key}><span>{labels[key]}</span><strong>{display(value)}<small>{["total_c", "hdl_c"].includes(key) ? latest.chol_unit : units[key]}</small></strong>{points.length > 1 && !["total_c", "hdl_c"].includes(key) && <svg viewBox="0 0 240 55" role="img" aria-label={`${labels[key]}历史趋势`}><polyline fill="none" stroke={spec.color} strokeWidth="2.5" points={points.map((p, i) => `${8 + i * 224 / (points.length - 1)},${45 - (p.value - min) / (max - min || 1) * 34}`).join(" ")}/>{points.map((p, i) => <circle key={p.date} cx={8 + i * 224 / (points.length - 1)} cy={45 - (p.value - min) / (max - min || 1) * 34} r="3" fill={spec.color}/>)}</svg>}<p>{points.length < 2 ? "记录不足两次，不判断趋势" : `${points[0].date} — ${points.at(-1)!.date}`}</p></article>; })}</div><p className="cs-fine">趋势仅描述测量变化；每项图形使用自身刻度，不代表疾病严重程度。</p></section>
      <section className="cs-card"><div className="cs-panel-title"><h2>体检时间线</h2><History size={19}/></div><div className="cs-timeline">{[...visits].reverse().map(v => <article key={v.date}><span className="cs-timeline-dot"/><time>{v.date}</time><div>{spec.metrics.map(k => <p key={k}><span>{labels[k]}</span><b>{display(v[k as keyof typeof v])} <small>{["total_c", "hdl_c"].includes(k) ? v.chol_unit : units[k]}</small></b></p>)}{system === "metabolic" && <p><span>既有结论</span><b>{display(v.glucose_status)}</b></p>}</div></article>)}</div></section>
      {system === "heart" ? <section className="cs-card cs-risk"><span className="cs-eyebrow">LOOKING AHEAD</span><h2>心血管长期风险</h2>{report.risk ? Object.entries(report.risk.horizons).map(([years, outcomes]) => <div key={years}><h3>未来 {years} 年</h3><div className="cs-risk-grid">{Object.entries(outcomes).map(([k, v]) => <article key={k}><span>{{ total_cvd: "总体心血管疾病", ascvd: "动脉粥样硬化性心血管疾病", heart_failure: "心力衰竭" }[k]}</span><b>{(v * 100).toFixed(2)}<small>%</small></b></article>)}</div></div>) : <div className="cs-warning"><b>本次未生成风险数值</b>{report.blockers.map(x => <p key={x}>{x}</p>)}</div>}<p className="cs-fine">PREVENT 长期估计，不是下一年患病概率；三项风险不可相加。60 岁及以上不提供 30 年估计。模型尚未在中国或九华人群验证。</p></section> : <section className="cs-scope-note"><ShieldCheck size={20}/><p>{system === "kidney" ? "此页展示 eGFR 历史与规则提醒，没有独立的肾病发病概率模型。单次指标不能用于确诊。" : "此页展示血糖历史与规则建议，没有独立的糖尿病发病概率模型；保留报告中已确认的结论。"}</p></section>}
    </div></div>;
}

function Plan({ report, scope, go, busy, save, showArchive }: { report: Report; scope: SystemKey | "all"; go: (p: string, k?: SystemKey) => void; busy: boolean; save: () => Promise<void>; showArchive: () => Promise<void> }) {
  const items = recommendations(report, scope);
  const all = scope === "all";
  return <><div className="cs-plan-grid"><aside className="cs-doctor-card"><span className="cs-eyebrow">YOUR NEXT CHAPTER</span><Doctor/><h2>让下一次检查，<br/>有的放矢。</h2><p>检查规划助手 · 建议待医学审核</p><div className="cs-window"><small>本次规划窗口</small><b>{report.planning_window[0]}<ArrowRight size={15}/>{report.planning_window[1]}</b></div><span className="cs-fine">医生插画为界面引导形象，不代表真人审核。</span></aside><section className="cs-plan-content"><div className="cs-panel-title"><div><span className="cs-eyebrow">{all ? "ALL RECOMMENDATIONS" : systems[scope].english}</span><h2>{all ? "所有建议，一处看清" : `${systems[scope].short}的下一步`}</h2></div><span className="cs-soft-tag">{items.length} 项建议</span></div>{report.input.source === "synthetic" && <p className="cs-warning">当前为人工构造示例，不是真实患者或效果验证。</p>}
      {report.input.as_of !== today() && <p className="cs-warning">此报告评估于 {report.input.as_of}，以下时间为当时的规划结果，不代表今天的新评估。</p>}
      {!items.length && <div className="cs-card"><h3>本次没有生成该范围的专项建议</h3><p>这不表示无需检查，也不代表健康结论。可查看整体规划，或补充资料后重新评估。</p></div>}
      {items.map((item, index) => <article className="cs-plan-item" key={item.code}><div className="cs-plan-number">{String(index + 1).padStart(2, "0")}</div><div><div className="cs-plan-item-title"><h3>{item.title}</h3><span>{item.decision}</span></div><p className="cs-reason">{item.reason}</p><div className="cs-schedule"><span>建议安排时间</span><b>{item.due_date ?? "待与医生确认具体时间"}</b><p>{!item.due_date ? "现有资料或规则未给出固定日期，不自动生成检查预约。" : item.due_date <= report.input.as_of ? "建议从本次评估时点开始核对或讨论，不等同于已预约检查。" : item.within_next_year ? "位于本次未来一年的规划窗口内，请结合既有医嘱安排。" : "参考日期在本次年度窗口之外，暂不自动列为年度必查；情况变化时需重新评估。"}</p></div><a className="cs-source" href={report.sources[item.source]?.url} target="_blank" rel="noreferrer">依据：{report.sources[item.source]?.title ?? item.basis} ↗</a></div></article>)}
      {!all && <button className="cs-primary cs-wide-button no-print" onClick={() => go("plan/all")}>汇总所有系统的检查建议<ArrowRight size={17}/></button>}
    </section></div>
    {all && <><div className="cs-report-tools no-print"><div><h2>把规划留给下一次自己</h2><p>保存本机报告快照，或通过浏览器打印为 PDF。</p></div><div><button disabled={busy || !!report.id} onClick={() => void save()}>{report.id ? <Check size={16}/> : <FileText size={16}/>} {report.id ? "报告已保存" : "保存报告"}</button><button onClick={() => window.print()}><ArrowDownToLine size={16}/>打印 / 保存 PDF</button><button onClick={() => void showArchive()}><History size={16}/>已保存规划</button></div></div><section className="cs-limitations"><h3>关于这份规划</h3><p>评估日期：{report.input.as_of} · {report.review_status} · {report.input.source === "synthetic" ? "人工构造资料" : "用户确认资料"}</p>{report.limitations.map(x => <p key={x}>{x}</p>)}</section></>}
  </>;
}




