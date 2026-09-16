import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function AiReportPage() {
  return (
    <PagePlaceholder
      title="AI 健康说明"
      description="将已经结构化和审核的结果转换为易懂语言，不生成新的医疗决策。"
      plannedCapabilities={["健康趋势摘要", "推荐解释", "证据链接", "LLM 模型标识"]}
    />
  );
}

