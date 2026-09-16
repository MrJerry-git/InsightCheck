import { ArrowRight, CheckCircle2, CircleDashed } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const pipeline = [
  "历年体检数据",
  "数据标准化",
  "纵向指标分析",
  "影像病灶匹配",
  "LightGBM 风险预测",
  "DeepFM 项目匹配",
  "医疗规则筛选",
  "三档体检方案",
  "LLM 解释",
];

const foundations = [
  { title: "前端路由与产品外壳", detail: "已建立完整页面入口和共享导航。" },
  { title: "后端分层与健康检查", detail: "API、Service、Repository 等目录职责已固定。" },
  { title: "可替换核心接口", detail: "RiskModel、RecommendationModel、RuleEngine、LLMProvider 已预留。" },
];

export default function DashboardPage() {
  return (
    <section className="space-y-8">
      <div className="space-y-3">
        <Badge>系统架构与工程骨架</Badge>
        <h1 className="max-w-4xl text-3xl font-bold tracking-tight sm:text-4xl">
          让每一项体检推荐都能追溯到历史证据、模型版本与规则决定
        </h1>
        <p className="max-w-3xl text-base leading-7 text-muted-foreground">
          当前只完成真实可运行的工程入口与模块接口。风险预测、项目匹配、医疗规则和自然语言解释将在后续阶段分别实现和验证。
        </p>
      </div>

      <Card className="bg-card/90">
        <CardHeader>
          <CardTitle>核心数据流</CardTitle>
          <CardDescription>各阶段职责独立，LLM 不参与最终项目决策。</CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
            {pipeline.map((stage, index) => (
              <li className="relative rounded-xl border bg-background/80 p-4" key={stage}>
                <div className="mb-6 flex items-center justify-between">
                  <span className="grid size-7 place-items-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                    {index + 1}
                  </span>
                  {index < pipeline.length - 1 && (
                    <ArrowRight
                      aria-hidden="true"
                      className="size-4 text-muted-foreground/60 md:absolute md:-right-2.5 md:top-5 md:z-10"
                    />
                  )}
                </div>
                <p className="font-semibold">{stage}</p>
                <p className="mt-1 text-xs text-muted-foreground">接口或页面已预留</p>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        {foundations.map((item) => (
          <Card className="bg-card/80" key={item.title}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CheckCircle2 aria-hidden="true" className="size-4 text-primary" />
                {item.title}
              </CardTitle>
            </CardHeader>
            <CardContent className="flex gap-2 text-sm text-muted-foreground">
              <CircleDashed aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              {item.detail}
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

