import type { EChartsOption } from "echarts";
import EChart from "./EChart";
import { buyHoldSeries, equityDates, equitySeries } from "../../data/mock";

export default function EquityCurve() {
  const option: EChartsOption = {
    backgroundColor: "transparent",
    grid: { left: 48, right: 16, top: 12, bottom: 24 },
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(13,18,32,0.95)",
      borderColor: "#2a3350",
      borderWidth: 1,
      textStyle: { color: "#e6eaf2", fontSize: 12 },
      valueFormatter: (v) => `$${Number(v).toLocaleString()}`,
    },
    xAxis: {
      type: "category",
      data: equityDates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: "#2a3350" } },
      axisTick: { show: false },
      axisLabel: { color: "#8a93a6", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      min: 10000,
      max: 30000,
      interval: 5000,
      axisLabel: {
        color: "#8a93a6",
        fontSize: 11,
        formatter: (v: number) => `$${v / 1000}K`,
      },
      splitLine: { lineStyle: { color: "#161d30" } },
    },
    series: [
      {
        name: "Equity",
        type: "line",
        data: equitySeries,
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        showSymbol: false,
        lineStyle: { color: "#8b5cf6", width: 2.5 },
        itemStyle: { color: "#8b5cf6" },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(139,92,246,0.40)" },
              { offset: 1, color: "rgba(139,92,246,0.02)" },
            ],
          },
        },
      },
      {
        name: "Buy & Hold",
        type: "line",
        data: buyHoldSeries,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: "#5b6478", width: 1.6, type: "dashed" },
        itemStyle: { color: "#5b6478" },
      },
    ],
  };
  return <EChart option={option} height="100%" />;
}
