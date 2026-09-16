"use client";

import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  RefreshCw,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { LesionSizeChart } from "@/components/imaging/lesion-size-chart";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { apiClient } from "@/services/api-client";
import type {
  LesionDemoAnalysis,
  LesionMatchDecision,
  LesionMatchStatus,
} from "@/types/lesion";

const statusLabels: Record<LesionMatchStatus, string> = {
  MATCHED: "已匹配",
  NEED_REVIEW: "需要复核",
  NEW_LESION: "新病灶 / 基线",
};

function statusVariant(status: LesionMatchStatus) {
  if (status === "MATCHED") return "default" as const;
  if (status === "NEED_REVIEW") return "destructive" as const;
  return "secondary" as const;
}

function formatSigned(value: number | null, suffix: string) {
  if (value === null) return "资料不足";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(1)}${suffix}`;
}

function confidenceLabel(match: LesionMatchDecision) {
  if (match.status === "NEW_LESION" && match.candidate_track_id === null) {
    return "无历史候选";
  }
  return `${(match.confidence * 100).toFixed(1)}%`;
}

export function LesionAnalysisPanel() {
  const [data, setData] = useState<LesionDemoAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await apiClient.getLesionDemoAnalysis());
    } catch {
      setError("无法加载病灶 Demo。请确认后端已启动并执行 python -m app.seed。");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .getLesionDemoAnalysis()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch(() => {
        if (!cancelled) {
          setError("无法加载病灶 Demo。请确认后端已启动并执行 python -m app.seed。");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <Card>
        <CardContent className="flex min-h-64 items-center justify-center text-muted-foreground">
          正在计算纵向病灶匹配与变化特征…
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card className="border-amber-300/80 bg-amber-50/70 dark:border-amber-800 dark:bg-amber-950/20">
        <CardContent className="flex min-h-56 flex-col items-center justify-center gap-4 text-center">
          <AlertTriangle className="size-8 text-amber-600" aria-hidden="true" />
          <p className="max-w-xl text-sm leading-6 text-amber-950 dark:text-amber-100">
            {error}
          </p>
          <button
            type="button"
            onClick={() => void loadData()}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          >
            <RefreshCw className="size-4" aria-hidden="true" />
            重新加载
          </button>
        </CardContent>
      </Card>
    );
  }

  const reviewMatches = data.matches.filter((item) => item.status === "NEED_REVIEW");
  const trend = data.trend;

  return (
    <div className="space-y-6">
      {reviewMatches.length > 0 && (
        <div className="flex gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">
          <AlertTriangle className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
          <div>
            <p className="font-semibold">存在 NEED_REVIEW 病灶</p>
            <p className="mt-1 leading-6">
              低置信度结果仅保留候选关系，不会自动并入既有病灶轨迹。
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="首末尺寸变化"
          value={formatSigned(trend.absolute_size_change, " mm")}
          detail={`相对变化 ${formatSigned(
            trend.relative_size_change === null ? null : trend.relative_size_change * 100,
            "%",
          )}`}
          icon={<TrendingUp className="size-4" aria-hidden="true" />}
        />
        <MetricCard
          label="年化变化率"
          value={formatSigned(trend.growth_rate, " mm/年")}
          detail="按首末观察间隔计算"
          icon={<TrendingUp className="size-4" aria-hidden="true" />}
        />
        <MetricCard
          label="连续出现次数"
          value={`${trend.continuous_occurrences} 次`}
          detail={`距最近检查 ${trend.months_since_last_exam.toFixed(0)} 个月`}
          icon={<CheckCircle2 className="size-4" aria-hidden="true" />}
        />
        <MetricCard
          label="分级变化"
          value={trend.grade_change}
          detail={trend.growing ? "描述性趋势：增大" : "未见明确增大趋势"}
          icon={
            trend.shrinking ? (
              <TrendingDown className="size-4" aria-hidden="true" />
            ) : (
              <CircleDot className="size-4" aria-hidden="true" />
            )
          }
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(22rem,0.65fr)]">
        <Card>
          <CardHeader>
            <CardTitle>尺寸趋势</CardTitle>
            <CardDescription>
              单位为毫米；数值来自结构化报告字段，不来自 CT 图片识别。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <LesionSizeChart observations={trend.observations} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>匹配解释</CardTitle>
            <CardDescription>评分组成、阈值决策和版本均由后端返回。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {trend.reasons.map((reason) => (
              <div key={reason} className="flex gap-2 text-sm leading-6">
                <CheckCircle2
                  className="mt-1 size-4 shrink-0 text-primary"
                  aria-hidden="true"
                />
                <span>{reason}</span>
              </div>
            ))}
            <div className="rounded-lg bg-muted p-3 font-mono text-xs text-muted-foreground">
              {trend.trend_version} · {data.track_id}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>病灶纵向时间轴</CardTitle>
          <CardDescription>
            右肺上叶 · 2023—2026 · 仅用于系统演示
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="relative grid gap-5 border-l border-border pl-6 lg:grid-cols-4 lg:border-l-0 lg:border-t lg:pl-0 lg:pt-6">
            {trend.observations.map((observation, index) => {
              const match = data.matches[index];
              return (
                <li key={observation.lesion_id} className="relative">
                  <span className="absolute -left-[1.78rem] top-1.5 size-3 rounded-full bg-primary ring-4 ring-background lg:-top-[1.82rem] lg:left-1" />
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-heading text-lg font-semibold">
                      {observation.exam_date.slice(0, 4)}
                    </span>
                    <Badge variant={statusVariant(match.status)}>
                      {statusLabels[match.status]}
                    </Badge>
                  </div>
                  <p className="mt-3 text-2xl font-semibold tabular-nums">
                    {observation.size_mm?.toFixed(1) ?? "—"}
                    <span className="ml-1 text-sm font-normal text-muted-foreground">mm</span>
                  </p>
                  <dl className="mt-3 space-y-1 text-xs text-muted-foreground">
                    <div className="flex justify-between gap-3">
                      <dt>分级</dt>
                      <dd>{observation.grade ?? "未记录"}</dd>
                    </div>
                    <div className="flex justify-between gap-3">
                      <dt>匹配置信度</dt>
                      <dd className="font-mono">{confidenceLabel(match)}</dd>
                    </div>
                  </dl>
                </li>
              );
            })}
          </ol>
        </CardContent>
      </Card>

      <div className="rounded-xl border border-dashed border-primary/35 bg-primary/5 p-4 text-sm leading-6 text-muted-foreground">
        <strong className="text-foreground">审核保护：</strong>
        当置信度处于 0.55–0.80 时显示 NEED_REVIEW，系统不会把该病灶静默视为同一轨迹。
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent>
        <div className="flex items-center gap-2 text-muted-foreground">
          {icon}
          <span className="text-xs font-medium tracking-wide uppercase">{label}</span>
        </div>
        <p className="mt-4 text-2xl font-semibold tabular-nums">{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}
