"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/services/api-client";
import type { ImportedHistory, ImportedPatient, ImportResult, ImportValidation } from "@/types/imports";

const errorText = (error: unknown) => error instanceof Error ? error.message : "操作失败，请重试";
const countText = (counts: Record<string, number>) =>
  `患者 ${counts.patients ?? 0} 名 · 记录 ${counts.encounters ?? 0} 次 · 观测 ${counts.observations ?? 0} 条`;

export function ImportPanel() {
  const [payload, setPayload] = useState<unknown>(null);
  const [validation, setValidation] = useState<ImportValidation | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [patients, setPatients] = useState<ImportedPatient[]>([]);
  const [history, setHistory] = useState<ImportedHistory | null>(null);
  const [selectedPatient, setSelectedPatient] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  async function loadFile(file?: File) {
    setPayload(null); setValidation(null); setResult(null); setError("");
    if (!file) return;
    setBusy(true);
    try {
      if (file.size > 18_000_000) throw new Error("文件超过 18 MB，请使用小型导入包。");
      const value: unknown = JSON.parse(await file.text());
      setValidation(await apiClient.validateImport(value));
      setPayload(value);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  async function importFile() {
    setBusy(true); setError("");
    try {
      setResult(await apiClient.importData(payload));
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  async function refreshPatients() {
    setBusy(true); setError(""); setHistory(null); setSelectedPatient("");
    try { setPatients(await apiClient.getImportedPatients()); setLoaded(true); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  async function selectPatient(id: string) {
    setSelectedPatient(id);
    setHistory(null); setError("");
    if (!id) return;
    setBusy(true);
    try { setHistory(await apiClient.getImportedHistory(id)); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="space-y-8" aria-busy={busy}>
      <section className="space-y-4 rounded-xl border bg-card p-6">
        <h2 className="text-xl font-semibold">导入合成历史记录</h2>
        <p className="text-sm text-muted-foreground">
          本入口只接收 Synthea 合成数据导入包，不接收真实体检资料。选择文件后先校验，确认后才写入。
        </p>
        <label className="block space-y-2">
          <span className="text-sm font-medium">选择已转换的导入包（JSON）</span>
          <input type="file" accept=".json,application/json" disabled={busy}
            onChange={(event) => void loadFile(event.target.files?.[0])}
            className="block max-w-full rounded-md border p-2 text-sm" />
        </label>
        <p className="text-xs text-muted-foreground">
          原始 ZIP 需先按仓库的导入说明转换；当前包含身高、体重、BMI 和血压五类观测。
        </p>
        {validation && (
          <div className="space-y-2" aria-live="polite">
            <p className="font-medium">{validation.valid ? "校验通过" : "校验未通过"} · {countText(validation.counts)}</p>
            {validation.issues.length > 0 && (
              <ul className="max-h-48 space-y-1 overflow-y-auto text-sm text-destructive">
                {validation.issues.slice(0, 50).map((issue, index) => (
                  <li key={index}>{issue.table} 第 {issue.row} 行 · {issue.field}：{issue.message}</li>
                ))}
              </ul>
            )}
            {validation.issues.length > 50 && <p>共 {validation.issues.length} 个问题，仅显示前 50 个。</p>}
          </div>
        )}
        <Button disabled={busy || !validation?.valid || result !== null} onClick={() => void importFile()}>
          确认导入
        </Button>
        {result && <div role="status" className="space-y-1 text-sm">
          <p>导入完成。新增：{countText(result.created)}</p>
          <p>已存在并复用：{countText(result.reused)}</p>
        </div>}
      </section>

      {error && <p role="alert" className="rounded-lg border border-destructive p-4 text-sm text-destructive">{error}</p>}
      {busy && <p role="status" className="text-sm text-muted-foreground">正在处理，请稍候…</p>}

      <section className="space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <h2 className="text-xl font-semibold">查看已导入记录</h2>
          <Button variant="outline" disabled={busy} onClick={() => void refreshPatients()}>加载患者列表</Button>
        </div>
        {loaded && <p className="text-sm text-muted-foreground">已加载 {patients.length} 名合成患者（最多 1,000 名）。</p>}
        <label className="block space-y-2">
          <span className="text-sm font-medium">选择合成患者</span>
          <select value={selectedPatient} disabled={busy || !patients.length}
            onChange={(event) => void selectPatient(event.target.value)} className="block w-full rounded-md border bg-background p-2 text-sm">
            <option value="">请选择患者</option>
            {patients.map((patient) => <option key={patient.id} value={patient.id}>{patient.anonymous_code}</option>)}
          </select>
        </label>
        {history && <div className="space-y-4">
          <p className="text-sm font-medium">合成数据 · {history.checks.length} 次历史记录</p>
          <p className="text-sm text-muted-foreground">原始数据没有报告可获得时间，也没有临床参考范围；以下数值不标记为正常或异常。</p>
          {history.truncated && <p className="text-sm">仅展示最近 100 次记录。</p>}
          {history.checks.map((check) => <article key={check.id} className="rounded-xl border bg-card p-4">
            <h3 className="mb-3 font-medium">{check.check_date} · wellness 记录</h3>
            {check.observations.length === 0 ? <p className="text-sm text-muted-foreground">本次没有五类已映射观测，不代表检查结果正常。</p> : (
              <div className="overflow-x-auto"><table className="w-full text-left text-sm">
                <thead><tr className="border-b"><th className="py-2">指标</th><th>数值</th><th>单位</th><th>观测时间</th></tr></thead>
                <tbody>{check.observations.map((observation) => <tr key={observation.id} className="border-b last:border-0">
                  <td className="py-2 pr-3">{observation.name}</td><td className="pr-3">{observation.value ?? "缺失"}</td>
                  <td className="pr-3">{observation.unit}</td><td className="whitespace-nowrap">{observation.event_time}</td>
                </tr>)}</tbody>
              </table></div>
            )}
          </article>)}
        </div>}
      </section>
    </div>
  );
}
