import Card from "../common/Card";
import Doughnut from "../chart/Doughnut";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import { useLive, type StrategyHealthData } from "../../lib/api";

const statusTone = (s?: string) => (s === "Healthy" ? "green" : s === "Degrading" ? "amber" : "red");
const sevClass = (s: string) => (s === "critical" ? "neg" : s === "warning" ? "amber" : "dim");

export default function StrategyHealth() {
  const { data, error } = useLive<StrategyHealthData>("/strategy/health", 5000);

  if (error && !data) {
    return (
      <Card title="Strategy Health">
        <div className="dim"><Icon name="warning" size={14} className="neg" /> Backend not reachable.</div>
      </Card>
    );
  }

  const h = data?.health;
  const b = data?.brain;
  const r = h?.recent;
  const slices = [
    { name: "Taken", value: b?.taken ?? 0, color: "#22c55e" },
    { name: "Blocked", value: b?.blocked ?? 0, color: "#ef4444" },
  ];

  return (
    <Card title="Strategy Health" subtitle={data?.strategy}
      right={<Badge text={h?.status ?? "—"} tone={statusTone(h?.status)} />}>
      <div className="grid-2-eq" style={{ alignItems: "center" }}>
        <div>
          <div className="card-subtitle" style={{ marginBottom: 6 }}>Brain filter — setups taken vs blocked</div>
          {(b?.total ?? 0) > 0 ? (
            <Doughnut data={slices} height={180} centerLabel="Block rate" centerValue={`${b?.block_rate ?? 0}%`}
              centerTone={(b?.block_rate ?? 0) > 50 ? "neg" : "default"} />
          ) : (
            <div className="dim ta-center" style={{ padding: 24 }}>No paper decisions yet — deploy a strategy to paper.</div>
          )}
        </div>
        <div className="risk-list">
          <div className="risk-item"><span className="dim">Taken / Blocked</span> <b>{b?.taken ?? 0} / {b?.blocked ?? 0}</b></div>
          <div className="risk-item"><span className="dim">Recent trades</span> <b>{r?.n ?? 0}</b></div>
          <div className="risk-item"><span className="dim">Win rate</span> <b>{((r?.win_rate ?? 0) * 100).toFixed(0)}%</b></div>
          <div className="risk-item"><span className="dim">Profit factor</span> <b className={(r?.profit_factor ?? 0) >= 1 ? "pos" : "neg"}>{(r?.profit_factor ?? 0).toFixed(2)}</b></div>
          <div className="risk-item"><span className="dim">Expectancy</span> <b className={(r?.expectancy ?? 0) >= 0 ? "pos" : "neg"}>{(r?.expectancy ?? 0).toFixed(2)}</b></div>
          <div className="risk-item"><span className="dim">Loss streak</span> <b>{r?.consecutive_losses ?? 0}</b></div>
        </div>
      </div>

      {Object.keys(b?.top_reasons ?? {}).length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="card-subtitle" style={{ marginBottom: 6 }}>Top block reasons</div>
          {Object.entries(b!.top_reasons).map(([reason, count]) => (
            <div key={reason} className="exec-line"><span className="exec-time">{count}×</span> {reason}</div>
          ))}
        </div>
      )}

      {(h?.warnings.length ?? 0) > 0 && (
        <div style={{ marginTop: 10 }}>
          {h!.warnings.map((w, i) => (
            <div key={i} className="risk-item" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <Icon name="warning" size={14} className={sevClass(w.severity)} />
              <span className={sevClass(w.severity)}>{w.detail}</span>
            </div>
          ))}
        </div>
      )}

      {((data?.breakdown.by_symbol.length ?? 0) > 0 || (data?.breakdown.by_session.length ?? 0) > 0) && (
        <div className="grid-2-eq" style={{ marginTop: 12 }}>
          {(data?.breakdown.by_symbol.length ?? 0) > 0 && (
            <div>
              <div className="card-subtitle" style={{ marginBottom: 6 }}>By symbol (worst first)</div>
              <div className="tablewrap">
                <table className="data-table">
                  <thead><tr><th>Symbol</th><th>Trades</th><th>Win%</th><th>Net P&amp;L</th><th>Blocked</th></tr></thead>
                  <tbody>
                    {data!.breakdown.by_symbol.map((s) => (
                      <tr key={s.name}>
                        <td><b>{s.name}</b></td>
                        <td>{s.trades}</td>
                        <td className="dim">{s.win_rate}%</td>
                        <td className={s.net_pnl >= 0 ? "pos" : "neg"}>{s.net_pnl >= 0 ? "+" : ""}{s.net_pnl.toFixed(2)}</td>
                        <td className="dim">{s.blocked}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {(data?.breakdown.by_session.length ?? 0) > 0 && (
            <div>
              <div className="card-subtitle" style={{ marginBottom: 6 }}>By session (UTC)</div>
              <div className="tablewrap">
                <table className="data-table">
                  <thead><tr><th>Session</th><th>Trades</th><th>Win%</th><th>Net P&amp;L</th></tr></thead>
                  <tbody>
                    {data!.breakdown.by_session.map((s) => (
                      <tr key={s.name}>
                        <td><b>{s.name}</b></td>
                        <td>{s.trades}</td>
                        <td className="dim">{s.win_rate}%</td>
                        <td className={s.net_pnl >= 0 ? "pos" : "neg"}>{s.net_pnl >= 0 ? "+" : ""}{s.net_pnl.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
