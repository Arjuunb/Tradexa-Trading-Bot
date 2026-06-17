import type { EChartsOption } from "echarts";
import EChart from "./EChart";
import { series as palette, tooltipStyle } from "./chartTheme";

interface Slice {
  name: string;
  value: number;
  color?: string;
}

interface DoughnutProps {
  data: Slice[];
  height?: number;
  /** Optional centred label/value (e.g. "Win Rate" / "62%"). */
  centerLabel?: string;
  centerValue?: string;
  centerTone?: "pos" | "neg" | "default";
}

/** Doughnut / ring chart with an optional centred KPI. */
export default function Doughnut({
  data, height = 180, centerLabel, centerValue, centerTone = "default",
}: DoughnutProps) {
  const option: EChartsOption = {
    tooltip: {
      trigger: "item",
      ...tooltipStyle,
      formatter: (p: any) => `${p.name}: ${p.value} (${p.percent}%)`,
    },
    series: [{
      type: "pie",
      radius: ["64%", "86%"],
      center: ["50%", "50%"],
      avoidLabelOverlap: false,
      label: { show: false },
      labelLine: { show: false },
      itemStyle: { borderColor: "#0d1322", borderWidth: 3 },
      data: data.map((d, i) => ({
        name: d.name,
        value: Math.max(d.value, 0.0001),
        itemStyle: { color: d.color ?? palette[i % palette.length] },
      })),
    }],
  };

  const toneColor = centerTone === "pos" ? "#22c55e" : centerTone === "neg" ? "#ef4444" : "#e6eaf2";
  return (
    <div style={{ position: "relative", height }}>
      <EChart option={option} height={height} />
      {(centerLabel || centerValue) && (
        <div style={{
          position: "absolute", inset: 0, display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center", pointerEvents: "none",
        }}>
          {centerLabel && <span style={{ color: "#8a93a6", fontSize: 12 }}>{centerLabel}</span>}
          {centerValue && <span style={{ color: toneColor, fontSize: 22, fontWeight: 600 }}>{centerValue}</span>}
        </div>
      )}
    </div>
  );
}
