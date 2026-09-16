import { Info } from "lucide-react";

export function MedicalDisclaimer() {
  return (
    <div className="flex gap-3 rounded-xl border border-amber-300/70 bg-amber-50/80 p-4 text-sm leading-6 text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">
      <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <p>
        本系统基于历史体检数据提供健康趋势分析与体检项目辅助推荐，不构成疾病诊断、医疗处方或治疗建议，最终体检方案应由具有资质的医务人员结合实际情况确认。
      </p>
    </div>
  );
}

