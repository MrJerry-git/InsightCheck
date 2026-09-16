import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function ModelsAdminPage() {
  return (
    <PagePlaceholder
      title="模型与流水线版本"
      description="管理特征流水线、风险模型、推荐模型和真实评估记录。"
      plannedCapabilities={["特征流水线版本", "风险模型版本", "推荐模型版本", "评估与发布状态"]}
    />
  );
}

