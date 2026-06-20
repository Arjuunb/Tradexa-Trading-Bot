import { useState } from "react";
import { Badge, PageHeader } from "../components/common/ui";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import CustomBuilder from "../components/strategy/CustomBuilder";
import { useApp } from "../app-context";
import { apiPostJson, useLive, type StrategyList, type StrategyPerformance } from "../lib/api";

function PreBuilt() {
  const app = useApp();
  const list = useLive<StrategyList>("/strategy/list", 5000);
  const perf = useLive<StrategyPerformance>("/strategy/performance", 4000);
  const active = list.data?.active;
  const [busy, setBusy] = useState<string | null>(null);

  const activate = async (key: string, label: string) => {
    setBusy(key);
    try {
      const r = await apiPostJson<any>("/strategy/select", { strategy: key });
      if (r?.error || r?.detail) app.toast(r.error || r.detail, "error");
      else { app.toast(`Activated ${label} — engine now trading it (paper)`, "success"); list.refetch(); }
    } catch { app.toast("Switching strategy needs the webhook secret", "error"); }
    finally { setBusy(null); }
  };

  return (
    <>
      {list.error && !list.data && (
        <div className="card" style={{ borderColor: "#ef4444" }}>
          <Icon name="warning" size={15} className="neg" /> Backend not reachable.
        </div>
      )}
      <div className="card">
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Strategy</th><th>Description</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(list.data?.strategies ?? []).map((s) => (
                <tr key={s.key}>
                  <td><b>{s.label}</b></td>
                  <td className="dim">{s.desc}</td>
                  <td>{s.key === active
                    ? <Badge text={`Active · ${list.data?.timeframe}`} tone="green" />
                    : <Badge text="Available" tone="default" />}</td>
                  <td style={{ textAlign: "right" }}>
                    {s.key === active
                      ? <span className="dim" style={{ fontSize: 12 }}><Icon name="check" size={13} /> in use</span>
                      : <button className="btn btn-soft sm" disabled={busy !== null} onClick={() => activate(s.key, s.label)}>
                          {busy === s.key ? "Activating…" : "Activate"}
                        </button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="dim" style={{ marginTop: 8 }}>
          Click <b>Activate</b> to switch the live engine to that strategy (paper mode) — the choice is
          saved and every symbol starts trading it. Validated reference (BTC/ETH 4h, walk-forward,
          fees+slippage): trend strategies profit factor ~1.2 out-of-sample.
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
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

export default function StrategiesPage() {
  const [tab, setTab] = useState<"Pre-built" | "Custom Builder">("Pre-built");

  return (
    <>
      <PageHeader title="Strategies" subtitle="choose a built-in strategy or build your own · paper mode" />
      <div className="tabs standalone">
        {(["Pre-built", "Custom Builder"] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === "Pre-built" ? <PreBuilt /> : <CustomBuilder />}
    </>
  );
}
