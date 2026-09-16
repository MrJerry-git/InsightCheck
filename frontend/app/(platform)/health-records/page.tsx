import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function HealthRecordsPage() {
  return (
    <PagePlaceholder
      title="历年体检记录"
      description="查看原始资料登记、结构化结果和数据标准化状态。"
      plannedCapabilities={["记录导入", "标准化状态", "异常与缺失提示", "来源证据追踪"]}
    />
  );
}

