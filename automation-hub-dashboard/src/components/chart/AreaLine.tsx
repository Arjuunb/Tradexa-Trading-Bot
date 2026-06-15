import type { EChartsOption } from "echarts";
import EChart from "./EChart";

interface Series { name: string; data: number[]; color: string; dashed?: boolean; }

interface AreaLineProps {
  labels: (string | number)[];
  series: Series[];
  height?: number | string;
  fill?: boolean;
  yFormatter?: (v: number) => string;
  valueFormatter?: (v: number) => string;
}

export default function AreaLine({ labels, series, height = "100%", fill = true, yFormatter, valueFormatter }: AreaLineProps) {
  const option: EChartsOption = {
    backgroundColor: "transparent",
    grid: { left: 50, right: 16, top: 14, bottom: 26 },
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(13,18,32,0.95)",
      borderColor: "#2a3350",
      textStyle: { color: "#e6eaf2", fontSize: 12 },
      valueFormatter: valueFormatter ? (v) => valueFormatter(Number(v)) : undefined,
    },
    legend: series.length > 1 ? { show: true, top: 0, right: 0, textStyle: { color: "#8a93a6", fontSize: 11 }, itemWidth: 14, itemHeight: 8 } : undefined,
    xAxis: {
      type: "category", data: labels, boundaryGap: false,
      axisLine: { lineStyle: { color: "#2a3350" } }, axisTick: { show: false },
      axisLabel: { color: "#8a93a6", fontSize: 11 },
    },
    yAxis: {
      type: "value", scale: true,
      axisLabel: { color: "#8a93a6", fontSize: 11, formatter: yFormatter ? (v: number) => yFormatter(v) : undefined },
      splitLine: { lineStyle: { color: "#161d30" } },
    },
    series: series.map((s) => ({
      name: s.name, type: "line", data: s.data, smooth: true, showSymbol: false,
      lineStyle: { color: s.color, width: 2.2, type: s.dashed ? "dashed" : "solid" },
      itemStyle: { color: s.color },
      areaStyle: fill && !s.dashed ? {
        color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [
          { offset: 0, color: `${s.color}55` }, { offset: 1, color: `${s.color}05` },
        ] },
      } : undefined,
    })),
  };
  return <EChart option={option} height={height} />;
}
