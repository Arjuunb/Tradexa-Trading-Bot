import type { EChartsOption } from "echarts";
import EChart from "./EChart";

interface Slice { name: string; value: number; color: string; }

interface DoughnutProps {
  data: Slice[];
  height?: number;
  centerLabel?: string;
  centerValue?: string;
  centerTone?: "pos" | "neg" | "default";
}

export default function Doughnut({ data, height = 180, centerLabel, centerValue, centerTone = "default" }: DoughnutProps) {
  const option: EChartsOption = {
    tooltip: { trigger: "item", backgroundColor: "rgba(13,18,32,0.95)", borderColor: "#2a2a2f", textStyle: { color: "#e6eaf2", fontSize: 12 }, formatter: (p: any) => `${p.name}: ${p.value} (${p.percent}%)` },
    series: [{
      type: "pie", radius: ["64%", "86%"], center: ["50%", "50%"], avoidLabelOverlap: false,
      label: { show: false }, labelLine: { show: false }, itemStyle: { borderColor: "#131315", borderWidth: 3 },
      data: data.map((d) => ({ name: d.name, value: Math.max(d.value, 0.0001), itemStyle: { color: d.color } })),
    }],
  };
  return (
    <div className="doughnut-wrap" style={{ height }}>
      <EChart option={option} height={height} />
      {(centerLabel || centerValue) && (
        <div className="doughnut-center">
          {centerLabel && <span className="doughnut-label">{centerLabel}</span>}
          {centerValue && <span className={`doughnut-value ${centerTone === "pos" ? "pos" : centerTone === "neg" ? "neg" : ""}`}>{centerValue}</span>}
        </div>
      )}
    </div>
  );
}
