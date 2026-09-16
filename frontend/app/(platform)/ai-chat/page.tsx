import { PagePlaceholder } from "@/components/shared/page-placeholder";

export default function AiChatPage() {
  return (
    <PagePlaceholder
      title="AI 问答"
      description="基于受控、结构化的患者上下文回答问题，不让 LLM 直接读取原始报告后推荐项目。"
      plannedCapabilities={["上下文问答", "引用证据", "安全提示", "对话审计"]}
    />
  );
}

