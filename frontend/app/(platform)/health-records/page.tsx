import { ImportPanel } from "@/components/imports/import-panel";

export default function HealthRecordsPage() {
  return (
    <section className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold">历年体检记录</h1>
        <p className="text-muted-foreground">校验合成数据，保留来源与原始观测，查看纵向历史。</p>
      </div>
      <ImportPanel />
    </section>
  );
}
