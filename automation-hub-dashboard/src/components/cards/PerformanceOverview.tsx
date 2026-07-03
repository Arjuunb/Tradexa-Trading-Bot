import Card from "../common/Card";
import Sparkline from "../chart/Sparkline";
import { useLive, type StrategyPerformance } from "../../lib/api";

const money = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

// Real performance from the live paper track record (no mock).
export default function PerformanceOverview() {
  const { data } = useLive<StrategyPerformance>("/strategy/performance", 4000);
  const d = data;
  const spark = (d?.equity_curve ?? []).map((p) => p.equity);

  const items: { label: string; value: string; tone: string; spark?: number[] }[] = [
    { label: "Win Rate", value: d ? `${d.win_rate.toFixed(1)}%` : "—", tone: "" },
    { label: "Profit Factor", value: d ? d.profit_factor.toFixed(2) : "—", tone: d && d.profit_factor >= 1 ? "green" : "red" },
    { label: "Total Trades", value: d ? String(d.trades) : "—", tone: "" },
    { label: "Realized P&L", value: d ? money(d.realized_pnl) : "—", tone: d && d.realized_pnl >= 0 ? "green" : "red", spark: spark.length > 1 ? spark : undefined },
    { label: "Expectancy", value: d ? money(d.expectancy) : "—", tone: d && d.expectancy >= 0 ? "green" : "red" },
    { label: "Best Trade", value: d ? money(d.best) : "—", tone: "green" },
    { label: "Worst Trade", value: d ? money(d.worst) : "—", tone: "red" },
    { label: "Max Drawdown", value: d ? `${d.max_drawdown_pct.toFixed(1)}%` : "—", tone: "red" },
  ];

  return (
    <Card title="Performance Overview" subtitle="live paper" className="perf-card">
      <div className="perf-grid">
        {items.map((p) => (
          <div className="perf-item" key={p.label}>
            <span className="perf-label">{p.label}</span>
            <div className="perf-value-row">
              <span className={`perf-value ${p.tone === "green" ? "pos" : p.tone === "red" ? "neg" : ""}`}>{p.value}</span>
              {p.spark && p.spark.length > 1 && (
                <div className="perf-spark"><Sparkline data={p.spark} color="#eab54f" height={24} /></div>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
