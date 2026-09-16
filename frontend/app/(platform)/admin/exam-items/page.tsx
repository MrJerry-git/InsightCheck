import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function ExamItemsAdminPage() {
  return (
    <PagePlaceholder
      title="体检项目管理"
      description="维护体检项目目录、功能分类和未来规则所需的项目属性。"
      plannedCapabilities={["项目目录", "功能分类", "项目属性", "启停与版本"]}
    />
  );
}

