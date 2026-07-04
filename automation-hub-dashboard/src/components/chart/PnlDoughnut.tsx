import type { EChartsOption } from "echarts";
import EChart from "./EChart";
import { useLive, type StrategyPerformance } from "../../lib/api";

const money = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export default function PnlDoughnut() {
  const { data } = useLive<StrategyPerformance>("/strategy/performance", 4000);
  const groups = [
    { name: "Winners", value: data?.wins ?? 0, color: "#22c55e" },
    { name: "Losers", value: data?.losses ?? 0, color: "#ef4444" },
    { name: "Breakeven", value: data?.breakeven ?? 0, color: "#5b6478" },
  ];

  const option: EChartsOption = {
    tooltip: {
      trigger: "item", backgroundColor: "rgba(13,18,32,0.95)", borderColor: "#2a2a2f",
      textStyle: { color: "#e6eaf2", fontSize: 12 },
      formatter: (p: any) => `${p.name}: ${p.value} (${p.percent}%)`,
    },
    series: [{
      type: "pie", radius: ["64%", "86%"], center: ["50%", "50%"],
      avoidLabelOverlap: false, label: { show: false }, labelLine: { show: false },
      itemStyle: { borderColor: "#131315", borderWidth: 3 },
      data: groups.map((g) => ({ name: g.name, value: Math.max(g.value, 0.0001), itemStyle: { color: g.color } })),
    }],
  };

  const realized = data?.realized_pnl ?? 0;
  return (
    <div className="doughnut-wrap">
      <EChart option={option} height={180} />
      <div className="doughnut-center">
        <span className="doughnut-label">Realized P&amp;L</span>
        <span className={`doughnut-value ${realized >= 0 ? "pos" : "neg"}`}>{money(realized)}</span>
      </div>
    </div>
  );
}
