import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function TrendsPage() {
  return (
    <PagePlaceholder
      title="纵向趋势"
      description="使用 ECharts 展示标准化后的跨年指标趋势与数据缺口。"
      plannedCapabilities={["单位一致性", "趋势图表", "参考范围变化", "数据缺口说明"]}
    />
  );
}

