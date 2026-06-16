import type { EChartsOption } from "echarts";
import EChart from "./EChart";
import { useLive, hhmmss, type EquityCurveData } from "../../lib/api";

export default function EquityCurve() {
  const { data } = useLive<EquityCurveData>("/paper/equity-curve", 3000);
  const points = data?.points ?? [];
  const labels = points.map((p, i) => (i === 0 ? "start" : hhmmss(p.t)));
  const series = points.map((p) => p.equity);
  const start = data?.starting_balance ?? 10000;

  const option: EChartsOption = {
    backgroundColor: "transparent",
    grid: { left: 56, right: 16, top: 12, bottom: 24 },
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(13,18,32,0.95)",
      borderColor: "#2a3350",
      borderWidth: 1,
      textStyle: { color: "#e6eaf2", fontSize: 12 },
      valueFormatter: (v) => `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`,
    },
    xAxis: {
      type: "category", data: labels, boundaryGap: false,
      axisLine: { lineStyle: { color: "#2a3350" } },
      axisTick: { show: false },
      axisLabel: { color: "#8a93a6", fontSize: 11 },
    },
    yAxis: {
      type: "value", scale: true,
      axisLabel: { color: "#8a93a6", fontSize: 11, formatter: (v: number) => `$${(v / 1000).toFixed(1)}K` },
      splitLine: { lineStyle: { color: "#161d30" } },
    },
    series: [
      {
        name: "Equity", type: "line", data: series, smooth: true,
        showSymbol: false, lineStyle: { color: "#8b5cf6", width: 2.5 },
        itemStyle: { color: "#8b5cf6" },
        markLine: {
          silent: true, symbol: "none",
          lineStyle: { color: "#5b6478", type: "dashed", width: 1.4 },
          data: [{ yAxis: start }],
          label: { color: "#8a93a6", fontSize: 10, formatter: "start" },
        },
        areaStyle: {
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(139,92,246,0.40)" },
              { offset: 1, color: "rgba(139,92,246,0.02)" },
            ],
          },
        },
      },
    ],
  };
  return <EChart option={option} height="100%" />;
}
