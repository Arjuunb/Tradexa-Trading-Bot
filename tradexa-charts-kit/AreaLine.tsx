import type { EChartsOption } from "echarts";
import EChart from "./EChart";
import { areaFill, categoryAxis, colors, grid, tooltipStyle, valueAxis } from "./chartTheme";

interface Series {
  name: string;
  data: number[];
  color: string;
  dashed?: boolean;
}

interface AreaLineProps {
  labels: (string | number)[];
  series: Series[];
  height?: number | string;
  fill?: boolean;
  /** Format y-axis tick labels, e.g. (v) => `$${v}`. */
  yFormatter?: (v: number) => string;
  /** Format the value shown in the tooltip. */
  valueFormatter?: (v: number) => string;
}

/** Smooth area/line chart. Pass one series for a single line, many for a legend. */
export default function AreaLine({
  labels, series, height = "100%", fill = true, yFormatter, valueFormatter,
}: AreaLineProps) {
  const option: EChartsOption = {
    backgroundColor: "transparent",
    grid,
    tooltip: {
      trigger: "axis",
      ...tooltipStyle,
      valueFormatter: valueFormatter ? (v) => valueFormatter(Number(v)) : undefined,
    },
    legend: series.length > 1
      ? { show: true, top: 0, right: 0, textStyle: { color: colors.textDim, fontSize: 11 },
          itemWidth: 14, itemHeight: 8 }
      : undefined,
    xAxis: categoryAxis(labels),
    yAxis: valueAxis(yFormatter),
    series: series.map((s) => ({
      name: s.name,
      type: "line",
      data: s.data,
      smooth: true,
      showSymbol: false,
      lineStyle: { color: s.color, width: 2.2, type: s.dashed ? "dashed" : "solid" },
      itemStyle: { color: s.color },
      areaStyle: fill && !s.dashed ? areaFill(s.color) : undefined,
    })),
  };
  return <EChart option={option} height={height} />;
}
