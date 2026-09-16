import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function RiskAnalysisPage() {
  return (
    <PagePlaceholder
      title="风险分析"
      description="未来展示 LightGBM 风险概率、特征贡献、证据与模型版本，不包装为确定诊断。"
      plannedCapabilities={["风险概率", "特征贡献", "证据引用", "模型与特征版本"]}
    />
  );
}

