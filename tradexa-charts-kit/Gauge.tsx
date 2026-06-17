import type { EChartsOption } from "echarts";
import EChart from "./EChart";
import { palette } from "./chartTheme";

interface GaugeProps {
  value: number;
  title?: string;
  max?: number;
  /** Draws a red threshold marker (e.g. a risk limit). */
  threshold?: number;
  color?: string;
  height?: number;
}

/** Single-value gauge — good for exposure %, risk usage, confidence, etc.
 *  When `threshold` is set, the arc past it turns red (e.g. a risk limit). */
export default function Gauge({
  value, title, max = 100, threshold, color = palette.purple, height = 220,
}: GaugeProps) {
  // Colour the track: base colour up to the threshold, red beyond it.
  const axisColor: [number, string][] = threshold !== undefined
    ? [[Math.min(1, threshold / max), color], [1, palette.red]]
    : [[1, "#1b2336"]];

  const option: EChartsOption = {
    series: [{
      type: "gauge",
      min: 0,
      max,
      progress: { show: true, width: 10, itemStyle: { color } },
      axisLine: { lineStyle: { width: 10, color: axisColor } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { color: "#8a93a6", fontSize: 10, distance: 12 },
      pointer: { show: false },
      anchor: { show: false },
      title: { color: "#8a93a6", fontSize: 12, offsetCenter: [0, "62%"] },
      detail: {
        color: "#e6eaf2", fontSize: 22, fontWeight: 600, offsetCenter: [0, "0%"],
        formatter: (v: number) => `${Math.round(v)}`,
      },
      data: [{ value, name: title ?? "" }],
    }],
  };
  return <EChart option={option} height={height} />;
}
