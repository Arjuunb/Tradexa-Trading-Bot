import type { EChartsOption } from "echarts";
import EChart from "./EChart";
import { pnlDistribution } from "../../data/mock";

export default function PnlDoughnut() {
  const data = pnlDistribution.groups.map((g) => ({
    name: g.name,
    value: Math.max(g.count, 0.0001),
    itemStyle: { color: g.color },
  }));

  const option: EChartsOption = {
    tooltip: {
      trigger: "item",
      backgroundColor: "rgba(13,18,32,0.95)",
      borderColor: "#2a3350",
      textStyle: { color: "#e6eaf2", fontSize: 12 },
      formatter: (p: any) => `${p.name}: ${p.percent}%`,
    },
    series: [
      {
        type: "pie",
        radius: ["64%", "86%"],
        center: ["50%", "50%"],
        avoidLabelOverlap: false,
        label: { show: false },
        labelLine: { show: false },
        itemStyle: { borderColor: "#0d1322", borderWidth: 3 },
        data,
      },
    ],
  };

  return (
    <div className="doughnut-wrap">
      <EChart option={option} height={180} />
      <div className="doughnut-center">
        <span className="doughnut-label">{pnlDistribution.totalLabel}</span>
        <span className="doughnut-value pos">{pnlDistribution.total}</span>
      </div>
    </div>
  );
}
