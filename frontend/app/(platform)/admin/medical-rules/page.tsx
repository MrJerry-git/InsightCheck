import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function MedicalRulesAdminPage() {
  return (
    <PagePlaceholder
      title="医疗规则管理"
      description="维护规则版本、适用范围和审核状态；本阶段不内置医疗规则。"
      plannedCapabilities={["规则版本", "适用范围", "冲突检查", "审核与发布状态"]}
    />
  );
}

