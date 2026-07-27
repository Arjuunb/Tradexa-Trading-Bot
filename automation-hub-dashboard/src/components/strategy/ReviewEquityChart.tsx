import type { EChartsOption } from "echarts";
import EChart from "../chart/EChart";

/**
 * Equity curve for the strategy review. Renders one series, or two when
 * comparing an original strategy against an optimised one.
 *
 * Both series are real backtest equity points — the comparison overlays two
 * actual runs over the same window, it does not model or extrapolate either.
 */
export default function ReviewEquityChart({ before, after, height = 220 }: {
  before: { equity: number }[];
  after?: { equity: number }[] | null;
  height?: number;
}) {
  const a = (before || []).map((p) => p.equity);
  const b = (after || []).map((p) => p.equity);
  if (a.length < 2) {
    return <div className="dim" style={{ padding: 12, fontSize: 12.5 }}>
      Not enough equity points to plot.</div>;
  }
  const len = Math.max(a.length, b.length);
  const labels = Array.from({ length: len }, (_, i) => (i === 0 ? "start" : `${i}`));

  const series: EChartsOption["series"] = [{
    name: b.length ? "Original" : "Equity",
    type: "line", data: a, showSymbol: false, smooth: true,
    lineStyle: { width: 1.8, color: b.length ? "#8a93a6" : "#089981" },
    areaStyle: b.length ? undefined : { color: "rgba(8,153,129,0.12)" },
  }];
  if (b.length) {
    series.push({
      name: "Optimised", type: "line", data: b, showSymbol: false, smooth: true,
      lineStyle: { width: 2, color: "#089981" },
      areaStyle: { color: "rgba(8,153,129,0.10)" },
    });
  }

  const option: EChartsOption = {
    backgroundColor: "transparent",
    grid: { left: 58, right: 14, top: b.length ? 28 : 12, bottom: 24 },
    legend: b.length ? { top: 0, right: 8, textStyle: { color: "#8a93a6", fontSize: 10 },
                         itemWidth: 14, itemHeight: 8, icon: "roundRect" } : undefined,
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(13,18,32,0.95)", borderColor: "#2a2a2f", borderWidth: 1,
      textStyle: { color: "#e6eaf2", fontSize: 12 },
      valueFormatter: (v) => `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`,
    },
    xAxis: {
      type: "category", data: labels, boundaryGap: false,
      axisLine: { lineStyle: { color: "#2a2a2f" } }, axisTick: { show: false },
      axisLabel: { color: "#8a93a6", fontSize: 10, hideOverlap: true },
      name: "trade #", nameTextStyle: { color: "#5b6478", fontSize: 9 },
    },
    yAxis: {
      type: "value", scale: true,
      axisLabel: { color: "#8a93a6", fontSize: 10,
                   formatter: (v: number) => `$${(v / 1000).toFixed(1)}k` },
      splitLine: { lineStyle: { color: "#161618" } },
    },
    series,
  };
  return <EChart option={option} height={height} />;
}
