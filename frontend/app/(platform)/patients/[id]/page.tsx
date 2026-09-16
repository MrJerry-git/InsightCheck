import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function PatientDetailPage() {
  return (
    <PagePlaceholder
      title="受检者详情"
      description="汇总单个受检者的历年记录、影像变化、风险与推荐追踪链。"
      plannedCapabilities={["基本信息与授权", "历年体检时间轴", "证据引用", "模型与规则版本"]}
    />
  );
}

