import { useState } from "react";
import Card from "../components/common/Card";
import AreaLine from "../components/chart/AreaLine";
import Icon from "../components/common/Icon";
import { Badge, PageHeader } from "../components/common/ui";
import { useApp } from "../app-context";
import { apiPostJson, useLive, type CustomSpec, type SimResult } from "../lib/api";
import { markDone } from "../lib/progress";

const money = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export default function SimulationPage() {
  const app = useApp();
  const saved = useLive<CustomSpec[]>("/strategy/custom", 6000);
  const [selId, setSelId] = useState<string>("");
  const [bars, setBars] = useState(3000);
  const [sim, setSim] = useState<SimResult | null>(null);
  const [running, setRunning] = useState(false);

  const specs = saved.data ?? [];
  const spec = specs.find((s) => s.id === selId) ?? specs[0];

  const run = async () => {
    if (!spec) return;
    setRunning(true);
    try {
      const res = await apiPostJson<SimResult>("/strategy/custom/simulate", { spec, bars });
      setSim(res);
      markDone("simulation");
      app.toast("Simulation complete — recorded for the safety flow", "success");
    } catch {
      app.toast("Simulation failed — backend unreachable?", "error");
    } finally {
      setRunning(false);
    }
  };

  const r = sim?.results;
  const curve = (r?.equity_curve ?? []).map((p) => p.equity);

  return (
    <>
      <PageHeader title="Simulation" subtitle="Forward simulation on historical data · step 2 of Backtest → Simulation → Paper → Live" />

      <Card title="Run a Simulation" right={<Badge text="SIMULATED DATA" tone="amber" />}>
        {specs.length === 0 ? (
          <div className="dim">No custom strategies to simulate. Build and save one on the <b>Strategies</b> page.</div>
        ) : (
          <div className="row-actions" style={{ justifyContent: "flex-start", gap: 10, flexWrap: "wrap" }}>
            <select value={spec?.id ?? ""} onChange={(e) => { setSelId(e.target.value); setSim(null); }} style={{ minWidth: 220 }}>
              {specs.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.symbol} {s.timeframe}</option>)}
            </select>
            <select value={bars} onChange={(e) => setBars(Number(e.target.value))}>
              {[1000, 2000, 3000, 5000].map((b) => <option key={b} value={b}>{b} bars</option>)}
            </select>
            <button className="btn btn-primary" disabled={running} onClick={run}>
              <Icon name="play" size={14} /> {running ? "Simulating…" : "Run Simulation"}
            </button>
          </div>
        )}
        <p className="dim" style={{ marginTop: 10 }}>
          <Icon name="info" size={13} /> Simulation data is kept separate from backtest, paper and live datasets — never shown as live performance.
        </p>
      </Card>

      {r && (
        <Card title="Simulation Result" subtitle={`${sim!.data_source} · ${sim!.symbol} ${sim!.timeframe} · ${r.span_days}d`}>
          <div className="perf-grid">
            {[
              ["Total Trades", String(r.total_trades), ""],
              ["Win Rate", `${r.win_rate}%`, ""],
              ["Profit Factor", r.profit_factor.toFixed(2), r.profit_factor >= 1 ? "pos" : "neg"],
              ["Net P&L", `${money(r.net_r)}R (${r.net_pct >= 0 ? "+" : ""}${r.net_pct}%)`, r.net_r >= 0 ? "pos" : "neg"],
              ["Max Drawdown", `${r.max_drawdown_pct}%`, "neg"],
              ["Avg R:R", r.avg_rr.toFixed(2), ""],
            ].map(([l, v, tone]) => (
              <div className="perf-item" key={l}><span className="perf-label">{l}</span><div className="perf-value-row"><span className={`perf-value ${tone}`}>{v}</span></div></div>
            ))}
          </div>
          {curve.length > 1 && (
            <div className="chart-md" style={{ marginTop: 12 }}>
              <AreaLine labels={curve.map((_, i) => String(i))} series={[{ name: "Equity", data: curve, color: "#8b5cf6" }]} valueFormatter={(x) => `$${x.toLocaleString()}`} />
            </div>
          )}
        </Card>
      )}
    </>
  );
}
