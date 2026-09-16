import { Construction } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type PagePlaceholderProps = {
  title: string;
  description: string;
  plannedCapabilities: string[];
  demo?: boolean;
};

export function PagePlaceholder({
  title,
  description,
  plannedCapabilities,
  demo = false,
}: PagePlaceholderProps) {
  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <p className="text-sm font-semibold text-primary">循影定检</p>
          <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
          <p className="max-w-3xl text-muted-foreground">{description}</p>
        </div>
        <Badge variant={demo ? "destructive" : "secondary"}>
          {demo ? "DEMO DATA" : "架构占位"}
        </Badge>
      </div>

      <Card className="max-w-3xl border-dashed bg-card/80">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Construction aria-hidden="true" className="size-4 text-primary" />
            本阶段未实现业务功能
          </CardTitle>
          <CardDescription>
            当前页面用于固定路由、导航和未来职责，未请求后端算法，也不会展示写死的医疗结论。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="grid gap-3 text-sm text-muted-foreground sm:grid-cols-2">
            {plannedCapabilities.map((capability) => (
              <li className="rounded-lg border bg-background/70 px-3 py-2" key={capability}>
                {capability}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </section>
  );
}

