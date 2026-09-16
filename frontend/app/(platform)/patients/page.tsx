import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function PatientsPage() {
  return (
    <PagePlaceholder
      title="受检者"
      description="统一管理受检者身份、授权范围和纵向档案入口。"
      plannedCapabilities={["受检者检索与筛选", "档案完整度", "数据授权状态", "纵向档案入口"]}
    />
  );
}

