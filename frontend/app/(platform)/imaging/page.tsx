import { LesionAnalysisPanel } from "@/components/imaging/lesion-analysis-panel";
import { MedicalDisclaimer } from "@/components/shared/medical-disclaimer";
import { Badge } from "@/components/ui/badge";

export default function ImagingPage() {
  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="mb-3 flex items-center gap-2">
            <Badge variant="secondary">DEMO DATA</Badge>
            <span className="text-xs text-muted-foreground">结构化报告输入</span>
          </div>
          <h1 className="font-heading text-3xl font-semibold tracking-tight">影像病灶随访</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            对已经结构化的影像报告病灶进行跨年匹配、变化分析和人工复核提示；不读取 CT 图片。
          </p>
        </div>
      </header>

      <LesionAnalysisPanel />
      <MedicalDisclaimer />
    </div>
  );
}
