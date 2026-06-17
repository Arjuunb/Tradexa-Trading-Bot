import type { EChartsOption } from "echarts";
import EChart from "./EChart";
import { categoryAxis, grid, palette, tooltipStyle, valueAxis } from "./chartTheme";

interface BarChartProps {
  labels: string[];
  data: number[];
  color?: string;
  height?: number | string;
  horizontal?: boolean;
  /** Green for values >= 0, red for < 0 (e.g. daily P&L). */
  diverging?: boolean;
  max?: number;
}

/** Bar chart. Set `diverging` for P&L-style green/red, `horizontal` for ranked lists. */
export default function BarChart({
  labels, data, color = palette.purple, height = "100%", horizontal, diverging, max,
}: BarChartProps) {
  const colored = data.map((v) => (diverging ? (v >= 0 ? palette.green : palette.red) : color));
  const cat = categoryAxis(labels);
  const val = { ...valueAxis(), max };

  const option: EChartsOption = {
    backgroundColor: "transparent",
    grid: { ...grid, left: horizontal ? 78 : 44 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tooltipStyle },
    xAxis: horizontal ? val : cat,
    yAxis: horizontal ? cat : val,
    series: [{
      type: "bar",
      data: data.map((v, i) => ({
        value: v,
        itemStyle: { color: colored[i], borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] },
      })),
      barWidth: "55%",
    }],
  };
  return <EChart option={option} height={height} />;
}
