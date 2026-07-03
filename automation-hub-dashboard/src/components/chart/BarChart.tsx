import type { EChartsOption } from "echarts";
import EChart from "./EChart";

interface BarChartProps {
  labels: string[];
  data: number[];
  color?: string;
  height?: number | string;
  horizontal?: boolean;
  diverging?: boolean; // green for >=0, red for <0
  max?: number;
}

export default function BarChart({ labels, data, color = "#eab54f", height = "100%", horizontal, diverging, max }: BarChartProps) {
  const colored = data.map((v) =>
    diverging ? (v >= 0 ? "#22c55e" : "#ef4444") : color,
  );
  const cat = { type: "category" as const, data: labels, axisLine: { lineStyle: { color: "#2a3350" } }, axisTick: { show: false }, axisLabel: { color: "#8a93a6", fontSize: 11 } };
  const val = { type: "value" as const, max, axisLabel: { color: "#8a93a6", fontSize: 11 }, splitLine: { lineStyle: { color: "#161d30" } } };
  const option: EChartsOption = {
    backgroundColor: "transparent",
    grid: { left: horizontal ? 78 : 44, right: 16, top: 12, bottom: 26 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: "rgba(13,18,32,0.95)", borderColor: "#2a3350", textStyle: { color: "#e6eaf2", fontSize: 12 } },
    xAxis: horizontal ? val : cat,
    yAxis: horizontal ? cat : val,
    series: [{
      type: "bar", data: data.map((v, i) => ({ value: v, itemStyle: { color: colored[i], borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] } })),
      barWidth: "55%",
    }],
  };
  return <EChart option={option} height={height} />;
}
