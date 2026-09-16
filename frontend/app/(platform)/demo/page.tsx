import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function DemoPage() {
  return (
    <PagePlaceholder
      demo
      title="演示环境"
      description="未来演示数据必须与真实模型实验结果严格区分，并在数据与页面上持续标记。"
      plannedCapabilities={["is_demo = true", "DEMO DATA 显著标识", "独立演示数据集", "禁止冒充真实指标"]}
    />
  );
}

