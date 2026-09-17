"use client";
import { useEffect, useState } from "react";
import { request } from "@/services/api-client";
import { Button } from "@/components/ui/button";

type Row = { id: string; code?: string; name?: string; category?: string; radiation?: boolean; rule_code?: string; enabled?: boolean; source?: string; version?: string; action?: string };
export function Catalog({ rules = false }: { rules?: boolean }) {
  const path = rules ? "/medical-rules" : "/exam-items";
  const [rows, setRows] = useState<Row[]>([]);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [source, setSource] = useState("");
  const [radiation, setRadiation] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const field = "rounded-md border bg-background p-2";
  useEffect(() => { let active = true; request<Row[]>(`${path}?limit=500`).then(r => { if (active) setRows(r); }).catch(e => { if (active) setError(String(e)); }); return () => { active = false; }; }, [path]);
  async function action(fn: () => Promise<unknown>) { setBusy(true); setError(""); try { await fn(); setRows(await request<Row[]>(`${path}?limit=500`)); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  return <div className="space-y-6"><h1 className="text-3xl font-bold">{rules ? "规则管理" : "检查项目目录"}</h1><p className="text-muted-foreground">{rules ? "首版支持建立资料缺失复核规则与启停。临床规则需另行审核；规则存在不等于已完成医学审核。" : "维护方案候选项目。费用尚未接入，模型匹配分数不代表项目必要性。"}</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    <form className="flex flex-wrap gap-3 rounded-xl border p-5" onSubmit={e => { e.preventDefault(); void action(() => request(path, {method: "POST", body: JSON.stringify(rules ? {rule_code: code, rule_type: "MISSING_DATA", condition_json: {required_fields: ["age", "gender"]}, action: "REVIEW_REQUIRED", priority: 10, source, version: "v1", enabled: true} : {code, name, category: "自定义项目", radiation, cost_level: "medium"})})); }}>
      <input aria-label="编码" className={field} required maxLength={64} value={code} onChange={e => setCode(e.target.value)} placeholder="唯一编码" />
      {rules ? <input aria-label="规则来源" className={field} required maxLength={300} value={source} onChange={e => setSource(e.target.value)} placeholder="来源与审核状态（如工程演示）" /> : <><input aria-label="项目名称" className={field} required maxLength={200} value={name} onChange={e => setName(e.target.value)} placeholder="项目名称" /><label><input type="checkbox" checked={radiation} onChange={e => setRadiation(e.target.checked)} /> 涉及辐射</label></>}
      <Button type="submit" disabled={busy}>{rules ? "添加缺失资料复核规则" : "添加项目"}</Button>
    </form>
    {rows.length === 0 && <p>尚未配置。可在工作台创建演示案例，或在此添加。</p>}
    {rows.map(r => <article key={r.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"><div><h2 className="font-semibold">{r.name || r.rule_code}</h2><p className="text-sm text-muted-foreground">{rules ? `${r.action} · ${r.source} · ${r.version}` : `${r.code} · ${r.category} · ${r.radiation ? "涉及辐射" : "无辐射标记"}`}</p></div>{rules && <Button variant="outline" disabled={busy} onClick={() => void action(() => request(`${path}/${r.id}`, {method: "PATCH", body: JSON.stringify({enabled: !r.enabled})}))}>{r.enabled ? "停用" : "启用"}</Button>}</article>)}
  </div>;
}
