import Card from "../common/Card";
import PnlDoughnut from "../chart/PnlDoughnut";
import { useLive, type StrategyPerformance } from "../../lib/api";

const money = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export default function PnlDistribution() {
  const { data } = useLive<StrategyPerformance>("/strategy/performance", 4000);
  const groups = [
    { name: "Winners", count: data?.wins ?? 0, value: money(data?.gross_win ?? 0), color: "#22c55e", pos: true },
    { name: "Losers", count: data?.losses ?? 0, value: money(-(data?.gross_loss ?? 0)), color: "#ef4444", pos: false },
    { name: "Breakeven", count: data?.breakeven ?? 0, value: "$0.00", color: "#5b6478", pos: null as boolean | null },
  ];

  return (
    <Card title="P&L Distribution" subtitle="live paper" className="pnl-dist-card">
      <div className="pnl-dist">
        <PnlDoughnut />
        <div className="pnl-legend">
          {groups.map((g) => (
            <div className="pnl-legend-item" key={g.name}>
              <span className="legend-dot" style={{ background: g.color }} />
              <span className="legend-name">{g.name} <span className="dim">({g.count})</span></span>
              <b className={g.pos === true ? "pos" : g.pos === false ? "neg" : "dim"}>{g.value}</b>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
