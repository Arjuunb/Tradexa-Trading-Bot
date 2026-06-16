import Card from "../components/common/Card";
import AreaLine from "../components/chart/AreaLine";
import Icon from "../components/common/Icon";
import { Badge, PageHeader, StatCard } from "../components/common/ui";
import { useLive, hhmmss, API_BASE, type StrategyPerformance } from "../lib/api";

const money = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export default function BacktestingPage(_props: { initialStrategy?: string }) {
  const { data, error } = useLive<StrategyPerformance>("/strategy/performance", 3000);
  const offline = error && !data;

  const curve = data?.equity_curve ?? [];
  const labels = curve.map((p, i) => (i === 0 ? "start" : hhmmss(p.t)));
  const equity = curve.map((p) => p.equity);

  return (
    <>
      <PageHeader
        title="Strategy Performance"
        subtitle={data ? `${data.strategy} · ${data.mode} · live paper-trading track record` : "live paper-trading track record"}
        actions={data ? <Badge text={`${data.trades} trades`} tone="blue" /> : undefined}
      />

      {offline && (
        <div className="card" style={{ borderColor: "#ef4444", display: "flex", alignItems: "center", gap: 10 }}>
          <Icon name="warning" size={16} className="neg" />
          <span><b>Backend not reachable.</b> Start the API at <span className="mono">{API_BASE}</span> — this page shows the bot's real executed trades.</span>
        </div>
      )}

      <div className="stat-row">
        <StatCard label="Realized P&L" value={money(data?.realized_pnl ?? 0)} tone={(data?.realized_pnl ?? 0) >= 0 ? "green" : "red"} sub={`Balance $${(data?.balance ?? 0).toLocaleString()}`} />
        <StatCard label="Win Rate" value={`${(data?.win_rate ?? 0).toFixed(1)}%`} />
        <StatCard label="Profit Factor" value={(data?.profit_factor ?? 0).toFixed(2)} tone={(data?.profit_factor ?? 0) >= 1 ? "green" : "red"} />
        <StatCard label="Max Drawdown" value={`${(data?.max_drawdown_pct ?? 0).toFixed(1)}%`} tone="amber" sub={money(-(data?.max_drawdown_abs ?? 0))} />
        <StatCard label="Worst Streak" value={`${data?.longest_losing_streak ?? 0}`} sub="losses in a row" />
      </div>

      <Card title="Equity Curve" subtitle="realized P&L of executed paper trades">
        <div className="chart-md">
          <AreaLine labels={labels} series={[{ name: "Equity", data: equity, color: "#8b5cf6" }]}
                    valueFormatter={(v) => `$${v.toLocaleString()}`} />
        </div>
      </Card>

      <div className="grid-2-1">
        <Card title="Trade Statistics" className="span-2">
          <div className="tablewrap">
            <table className="data-table">
              <tbody>
                <tr><td className="dim">Expectancy / trade</td><td className={(data?.expectancy ?? 0) >= 0 ? "pos" : "neg"}>{money(data?.expectancy ?? 0)}</td>
                    <td className="dim">Avg win</td><td className="pos">{money(data?.avg_win ?? 0)}</td></tr>
                <tr><td className="dim">Total trades</td><td>{data?.trades ?? 0}</td>
                    <td className="dim">Avg loss</td><td className="neg">{money(data?.avg_loss ?? 0)}</td></tr>
                <tr><td className="dim">Best trade</td><td className="pos">{money(data?.best ?? 0)}</td>
                    <td className="dim">Worst trade</td><td className="neg">{money(data?.worst ?? 0)}</td></tr>
              </tbody>
            </table>
          </div>
          <p className="dim" style={{ marginTop: 8 }}>
            Validated reference (BTC/ETH 4h, walk-forward, fees + slippage): profit factor ~1.2, ~15%/yr, ~14% max drawdown.
          </p>
        </Card>

        <Card title="Recent Trades">
          <div className="tablewrap">
            <table className="data-table">
              <thead><tr><th>Symbol</th><th>P&amp;L</th><th>R:R</th></tr></thead>
              <tbody>
                {(data?.recent ?? []).map((t) => (
                  <tr key={t.id}>
                    <td><b>{t.symbol}</b></td>
                    <td className={(t.pnl ?? 0) >= 0 ? "pos" : "neg"}>{money(t.pnl ?? 0)}</td>
                    <td className="dim">{t.rr !== null && t.rr !== undefined ? `${t.rr.toFixed(2)}R` : "—"}</td>
                  </tr>
                ))}
                {(data?.recent?.length ?? 0) === 0 && <tr><td colSpan={3} className="dim ta-center" style={{ padding: 16 }}>No closed trades yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}
