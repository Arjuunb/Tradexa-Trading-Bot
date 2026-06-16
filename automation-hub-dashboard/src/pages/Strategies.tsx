import { Badge, PageHeader } from "../components/common/ui";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { useLive, type StrategyList, type StrategyPerformance } from "../lib/api";

// Real strategies the engine can run, plus the live performance of the active one.
export default function StrategiesPage() {
  const list = useLive<StrategyList>("/strategy/list", 5000);
  const perf = useLive<StrategyPerformance>("/strategy/performance", 4000);
  const active = list.data?.active;

  return (
    <>
      <PageHeader title="Strategies" subtitle="engine strategies · paper mode" />

      {list.error && !list.data && (
        <div className="card" style={{ borderColor: "#ef4444" }}>
          <Icon name="warning" size={15} className="neg" /> Backend not reachable.
        </div>
      )}

      <div className="card">
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Strategy</th><th>Description</th><th>Status</th></tr></thead>
            <tbody>
              {(list.data?.strategies ?? []).map((s) => (
                <tr key={s.key}>
                  <td><b>{s.label}</b></td>
                  <td className="dim">{s.desc}</td>
                  <td>{s.key === active
                    ? <Badge text={`Active · ${list.data?.timeframe}`} tone="green" />
                    : <Badge text="Available" tone="default" />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="dim" style={{ marginTop: 8 }}>
          The active strategy is set on the backend (HUB_AUTO_STRATEGY). Validated reference
          (BTC/ETH 4h, walk-forward, fees+slippage): trend strategies profit factor ~1.2 out-of-sample.
        </p>
      </div>

      {perf.data && (
        <Card title={`Live Performance — ${perf.data.strategy}`} subtitle={`${perf.data.mode} · ${perf.data.trades} paper trades`}>
          <div className="tablewrap">
            <table className="data-table">
              <tbody>
                <tr><td className="dim">Win rate</td><td>{perf.data.win_rate.toFixed(1)}%</td>
                    <td className="dim">Profit factor</td><td className={perf.data.profit_factor >= 1 ? "pos" : "neg"}>{perf.data.profit_factor.toFixed(2)}</td></tr>
                <tr><td className="dim">Realized P&amp;L</td><td className={perf.data.realized_pnl >= 0 ? "pos" : "neg"}>${perf.data.realized_pnl.toFixed(2)}</td>
                    <td className="dim">Max drawdown</td><td className="amber">{perf.data.max_drawdown_pct.toFixed(1)}%</td></tr>
                <tr><td className="dim">Expectancy</td><td>${perf.data.expectancy.toFixed(2)}/trade</td>
                    <td className="dim">Worst streak</td><td>{perf.data.longest_losing_streak} losses</td></tr>
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
