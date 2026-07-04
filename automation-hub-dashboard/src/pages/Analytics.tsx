import Card from "../components/common/Card";
import AreaLine from "../components/chart/AreaLine";
import BarChart from "../components/chart/BarChart";
import Doughnut from "../components/chart/Doughnut";
import Icon from "../components/common/Icon";
import StrategyHealth from "../components/cards/StrategyHealth";
import { PageHeader, StatCard } from "../components/common/ui";
import { useLive, hhmmss, API_BASE, type PaperTradeRow, type StrategyPerformance } from "../lib/api";
import ReportsHub from "../components/reports/ReportsHub";

const money = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

// Group closed trades into per-day realized P&L (real data, not faked).
function dailyPnl(trades: PaperTradeRow[]): { days: string[]; pnl: number[] } {
  const agg = new Map<string, number>();
  for (const t of trades) {
    const d = (t.closed_at ?? "").slice(0, 10);
    if (d) agg.set(d, (agg.get(d) ?? 0) + (t.pnl ?? 0));
  }
  const days = [...agg.keys()].sort();
  return { days, pnl: days.map((d) => Math.round((agg.get(d) ?? 0) * 100) / 100) };
}

export default function AnalyticsPage() {
  const { data, error } = useLive<StrategyPerformance>("/strategy/performance", 3000);
  const { data: trades } = useLive<PaperTradeRow[]>("/paper/trades", 3000);
  const offline = error && !data;

  const curve = data?.equity_curve ?? [];
  const labels = curve.map((p, i) => (i === 0 ? "start" : hhmmss(p.t)));
  const equity = curve.map((p) => p.equity);
  const { days, pnl } = dailyPnl(trades ?? []);

  const wls = [
    { name: "Wins", value: data?.wins ?? 0, color: "#22c55e" },
    { name: "Losses", value: data?.losses ?? 0, color: "#ef4444" },
    { name: "Breakeven", value: data?.breakeven ?? 0, color: "#5b6478" },
  ];

  return (
    <>
      <PageHeader title="Analytics" subtitle="Performance over the bot's real paper-trade history" />

      <ReportsHub />

      {offline && (
        <div className="card" style={{ borderColor: "#ef4444", display: "flex", alignItems: "center", gap: 10 }}>
          <Icon name="warning" size={16} className="neg" />
          <span><b>Backend not reachable.</b> Start the API at <span className="mono">{API_BASE}</span> to see live analytics.</span>
        </div>
      )}

      <div className="stat-row">
        <StatCard label="Total Trades" value={String(data?.trades ?? 0)} />
        <StatCard label="Win Rate" value={`${(data?.win_rate ?? 0).toFixed(1)}%`} />
        <StatCard label="Profit Factor" value={(data?.profit_factor ?? 0).toFixed(2)} tone={(data?.profit_factor ?? 0) >= 1 ? "green" : "red"} />
        <StatCard label="Expectancy" value={money(data?.expectancy ?? 0)} tone={(data?.expectancy ?? 0) >= 0 ? "green" : "red"} />
        <StatCard label="Max Drawdown" value={`${(data?.max_drawdown_pct ?? 0).toFixed(1)}%`} tone="amber" />
      </div>

      <div className="grid-2-1">
        <Card title="Equity Curve" subtitle="realized P&L of executed paper trades" className="span-2">
          <div className="chart-md">
            <AreaLine labels={labels} series={[{ name: "Equity", data: equity, color: "#eab54f" }]}
                      valueFormatter={(v) => `$${v.toLocaleString()}`} />
          </div>
        </Card>

        <Card title="Win / Loss">
          <Doughnut data={wls} height={200} centerLabel="Win Rate" centerValue={`${(data?.win_rate ?? 0).toFixed(0)}%`}
                    centerTone={(data?.win_rate ?? 0) >= 50 ? "pos" : "default"} />
        </Card>
      </div>

      <StrategyHealth />

      <Card title="Daily P&L" subtitle="realized P&L grouped by close date">
        {days.length > 0 ? (
          <div className="chart-sm">
            <BarChart labels={days} data={pnl} diverging />
          </div>
        ) : (
          <div className="dim ta-center" style={{ padding: 24 }}>No closed trades yet.</div>
        )}
      </Card>
    </>
  );
}
