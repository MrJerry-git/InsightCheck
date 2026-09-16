"use client";

import type { EChartsOption, EChartsType } from "echarts";
import { useEffect, useRef } from "react";

import type { LesionTrendPoint } from "@/types/lesion";

interface LesionSizeChartProps {
  observations: LesionTrendPoint[];
}

export function LesionSizeChart({ observations }: LesionSizeChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let chart: EChartsType | undefined;
    let resizeObserver: ResizeObserver | undefined;
    let cancelled = false;

    async function renderChart() {
      const echarts = await import("echarts");
      if (cancelled || !containerRef.current) return;

      chart = echarts.init(containerRef.current);
      const option: EChartsOption = {
        animationDuration: 500,
        color: ["#147d72"],
        grid: { top: 28, right: 22, bottom: 42, left: 48 },
        tooltip: {
          trigger: "axis",
          valueFormatter: (value) => `${Number(value).toFixed(1)} mm`,
        },
        xAxis: {
          type: "category",
          boundaryGap: false,
          data: observations.map((item) => item.exam_date.slice(0, 4)),
          axisLine: { lineStyle: { color: "#9bb8b3" } },
          axisTick: { show: false },
        },
        yAxis: {
          type: "value",
          name: "尺寸 / mm",
          min: (value) => Math.max(0, Math.floor(value.min - 1)),
          splitLine: { lineStyle: { color: "rgba(120, 151, 145, 0.18)" } },
        },
        series: [
          {
            name: "病灶尺寸",
            type: "line",
            smooth: 0.25,
            symbol: "circle",
            symbolSize: 9,
            lineStyle: { width: 3 },
            areaStyle: { color: "rgba(20, 125, 114, 0.10)" },
            data: observations.map((item) => item.size_mm),
          },
        ],
      };
      chart.setOption(option);

      resizeObserver = new ResizeObserver(() => chart?.resize());
      resizeObserver.observe(containerRef.current);
    }

    void renderChart();
    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      chart?.dispose();
    };
  }, [observations]);

  return (
    <div
      ref={containerRef}
      className="h-72 w-full"
      role="img"
      aria-label="2023 至 2026 年病灶尺寸变化折线图"
    />
  );
}
