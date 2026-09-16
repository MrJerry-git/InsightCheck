import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function RecommendationsPage() {
  return (
    <PagePlaceholder
      title="体检方案"
      description="未来展示经过 DeepFM 评分和医疗规则筛选后的精简、标准、深入三档方案。"
      plannedCapabilities={["三档方案", "候选匹配评分", "规则筛选摘要", "医务人员确认状态"]}
    />
  );
}

