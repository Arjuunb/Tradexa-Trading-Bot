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
  const wins = data?.wins ?? 0, losses = data?.losses ?? 0;
  const total = Math.max(1, wins + losses);

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

      {/* win/loss ratio bar + key stats — fills the card */}
      <div className="ls-bar" style={{ marginTop: 12 }}>
        <div className="ls-long" style={{ width: `${(wins / total) * 100}%` }} />
        <div className="ls-short" style={{ width: `${(losses / total) * 100}%` }} />
      </div>
      <div className="row-actions" style={{ justifyContent: "space-between", marginTop: 6, fontSize: 12 }}>
        <span className="pos">{((wins / total) * 100).toFixed(0)}% win</span>
        <span className="dim">{data?.trades ?? 0} trades</span>
        <span className="neg">{((losses / total) * 100).toFixed(0)}% loss</span>
      </div>
      <div className="perf-grid" style={{ marginTop: 12 }}>
        {([
          ["Profit Factor", (data?.profit_factor ?? 0).toFixed(2), (data?.profit_factor ?? 0) >= 1 ? "pos" : "neg"],
          ["Expectancy", money(data?.expectancy ?? 0), (data?.expectancy ?? 0) >= 0 ? "pos" : "neg"],
          ["Avg Win", money(data?.avg_win ?? 0), "pos"],
          ["Avg Loss", money(-Math.abs(data?.avg_loss ?? 0)), "neg"],
          ["Best", money(data?.best ?? 0), "pos"],
          ["Worst", money(-Math.abs(data?.worst ?? 0)), "neg"],
        ] as [string, string, string][]).map(([l, v, t]) => (
          <div className="perf-item" key={l}><span className="perf-label">{l}</span><div className="perf-value-row"><span className={`perf-value ${t}`}>{v}</span></div></div>
        ))}
      </div>
    </Card>
  );
}
