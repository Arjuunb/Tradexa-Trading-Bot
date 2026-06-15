import type { EChartsOption } from "echarts";
import EChart from "./EChart";

interface SparklineProps {
  data: number[];
  color?: string;
  height?: number;
}

export default function Sparkline({ data, color = "#22c55e", height = 36 }: SparklineProps) {
  const option: EChartsOption = {
    animation: false,
    grid: { left: 0, right: 0, top: 2, bottom: 2 },
    xAxis: { type: "category", show: false, boundaryGap: false },
    yAxis: { type: "value", show: false, scale: true },
    series: [
      {
        type: "line",
        data,
        smooth: true,
        symbol: "none",
        lineStyle: { color, width: 2 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: `${color}55` },
              { offset: 1, color: `${color}00` },
            ],
          },
        },
      },
    ],
  };
  return <EChart option={option} height={height} />;
}
