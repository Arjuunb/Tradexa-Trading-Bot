import { useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { PageHeader, StatCard } from "../components/common/ui";
import { apiPostJson, useLive, type BotSettings, type PaperTradeRow, type SystemStatus, type BrokerList, type FillModelStatus } from "../lib/api";
import { Badge } from "../components/common/ui";
import { useApp } from "../app-context";
import { getProgress } from "../lib/progress";

function riskValid(s: BotSettings | null): boolean {
  if (!s) return false;
  const e = s.editable;
  return e.risk_per_trade_pct > 0 && e.risk_per_trade_pct <= 0.05
    && e.max_drawdown_pct > 0 && e.max_open_positions >= 1;
}

export default function LiveTradingPage() {
  const app = useApp();
  const { data: sys } = useLive<SystemStatus>("/system/status", 3000);
  const { data: settings } = useLive<BotSettings>("/settings", 5000);
  const { data: trades } = useLive<PaperTradeRow[]>("/paper/trades", 4000);
  const [confirmed, setConfirmed] = useState(false);

  const prog = getProgress();
  const brokerConnected = !!(sys?.broker_connected ?? settings?.readonly?.broker_connected);
  const checklist: [string, boolean][] = [
    ["Valid backtest results", prog.backtest],
    ["Simulation results recorded", prog.simulation],
    ["Paper-trading performance", (trades?.length ?? 0) > 0],
    ["Risk settings valid", riskValid(settings ?? null)],
    ["Broker / exchange connected", brokerConnected],
    ["Manual live confirmation", confirmed],
  ];
  const allPassed = checklist.every(([, ok]) => ok);

  return (
    <>
      <PageHeader title="Live Trading" subtitle="Locked until the full safety flow passes and a broker is connected"
        actions={<button className="btn btn-soft btn-sm" onClick={() => app.go("Safety Center")}>Safety Center</button>} />

      <Card title="Why live is locked" right={<span className="ui-badge" style={{ background: "#ef444422", color: "#ef4444" }}>LOCKED</span>}>
        <p style={{ lineHeight: 1.6 }}>
          New strategies can <b>never</b> go straight to live. The required flow is
          {" "}<b>Backtest → Simulation → Paper Trading → Live Trading</b>. Live trading stays
          disabled until every check below passes and a real broker / exchange is connected.
        </p>
      </Card>

      <Card title="Pre-flight Checklist">
        <div className="risk-list">
          {checklist.map(([label, ok]) => (
            <div className="risk-item" key={label} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <Icon name={ok ? "check" : "lock"} size={16} className={ok ? "pos" : "neg"} />
              <span className={ok ? "" : "dim"}>{label}</span>
            </div>
          ))}
        </div>

        <label className="row-actions" style={{ justifyContent: "flex-start", gap: 8, marginTop: 14, cursor: "pointer" }}>
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>I manually confirm I want to enable live trading.</span>
        </label>

        {!brokerConnected && (
          <p className="dim" style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <Icon name="warning" size={14} className="amber" /> No broker / exchange is connected. Live trading is hardware-locked by design until a real integration is configured.
          </p>
        )}

        <div className="row-actions" style={{ justifyContent: "flex-start", marginTop: 14 }}>
          <button className="btn btn-danger" disabled={!allPassed || !brokerConnected}
            title={brokerConnected ? "" : "Disabled until a real broker connection exists"}>
            <Icon name="rocket" size={14} /> Enable Live Trading
          </button>
        </div>
        {allPassed && !brokerConnected && (
          <p className="dim" style={{ marginTop: 8 }}>All software gates pass — only a real broker connection is missing.</p>
        )}
      </Card>

      <div className="grid-2-eq">
        <BrokerConnections />
        <FillModelControl />
      </div>

      <ExecutionQuality />
    </>
  );
}

function ExecutionQuality() {
  const app = useApp();
  const { data: sys } = useLive<SystemStatus>("/system/status", 8000);
  const fm = useLive<FillModelStatus>("/execution/fill-model", 8000).data;
  const live = !!sys?.broker_connected;
  const cost = fm?.round_trip_cost_pct;
  return (
    <Card title="Execution Quality" subtitle="how much execution frictions cost you — modeled today, measured once live">
      <div className="stat-row" style={{ marginBottom: 10 }}>
        <StatCard label="Source" value={live ? "Live venue" : "Modeled"} tone={live ? "green" : "amber"} sub={live ? "real fills" : "paper simulation"} />
        <StatCard label="Modeled round-trip cost" value={cost != null ? `${cost}%` : fm?.model === "perfect" ? "0% (perfect)" : "—"} sub="spread + slippage" />
        <StatCard label="Assumed slippage" value={fm ? `${((fm.slippage_pct ?? 0) * 100).toFixed(3)}%` : "—"} sub={`spread ${fm ? ((fm.spread_pct ?? 0) * 100).toFixed(3) : "—"}%`} />
        <StatCard label="Reject rate" value={fm ? `${((fm.reject_prob ?? 0) * 100).toFixed(1)}%` : "—"} sub="orders rejected" />
      </div>
      <div className="banner" style={{ fontSize: 12 }}>
        <Icon name="info" size={13} className="amber" />
        <span>
          <b>Real per-venue telemetry — latency, realised slippage and fill rate — activates when a live broker is connected.</b>{" "}
          Live trading is locked until the safety flow passes, so these figures are the <b>simulated</b> execution model, not measured venue data (nothing here is fabricated).
          See the modeled impact on a real run in <button className="chip-btn" onClick={() => app.go("Backtesting")}>Backtesting → Execution Realism</button>.
        </span>
      </div>
    </Card>
  );
}

function BrokerConnections() {
  const b = useLive<BrokerList>("/brokers", 10000).data;
  return (
    <Card title="Broker Connections" subtitle="one interface · Binance · Bybit · IBKR · Alpaca"
      right={b && <Badge text={b.live_locked ? "live locked" : "live unlocked"} tone={b.live_locked ? "amber" : "green"} />}>
      {!b ? <div className="dim">—</div> : (
        <>
          <div className="risk-list">
            {(b.brokers ?? []).map((br) => (
              <div className="risk-item" key={br.kind}>
                <span><b>{br.name}</b> <span className="dim" style={{ fontSize: 11 }}>· {br.mode}</span></span>
                <Badge text={br.connected ? (br.kind === "paper" ? "Executable" : "Connected") : "Not connected"}
                  tone={br.connected ? (br.kind === "paper" ? "green" : "blue") : "default"} />
              </div>
            ))}
          </div>
          <p className="dim" style={{ fontSize: 12, marginTop: 8 }}><Icon name="lock" size={12} /> {b.note}</p>
        </>
      )}
    </Card>
  );
}

function FillModelControl() {
  const app = useApp();
  const fm = useLive<FillModelStatus>("/execution/fill-model", 8000);
  const d = fm.data;
  const set = async (model: string) => {
    try { const r = await apiPostJson<any>("/execution/fill-model", { model, spread_pct: 0.0004, slippage_pct: 0.0003, reject_prob: model === "realistic" ? 0.01 : 0 });
      if (r?.error || r?.detail) app.toast(r.error || r.detail, "error"); else { app.toast(`Fill model: ${model}`, "success"); fm.refetch(); } }
    catch { app.toast("Switching the fill model needs the webhook secret", "error"); }
  };
  return (
    <Card title="Execution Fill Model" subtitle="how realistically the paper engine fills orders"
      right={d && <Badge text={d.model} tone={d.model === "realistic" ? "amber" : "green"} />}>
      <p className="dim" style={{ fontSize: 13 }}>{d?.note ?? "—"}</p>
      {d?.model === "realistic" && (
        <div className="risk-list" style={{ marginTop: 6 }}>
          <div className="risk-item"><span className="dim">Round-trip cost</span> <b>{d.round_trip_cost_pct}%</b></div>
          <div className="risk-item"><span className="dim">Spread / slippage</span> <b>{(d.spread_pct ?? 0) * 100}% / {(d.slippage_pct ?? 0) * 100}%</b></div>
          <div className="risk-item"><span className="dim">Reject probability</span> <b>{(d.reject_prob ?? 0) * 100}%</b></div>
        </div>
      )}
      <div className="row-actions" style={{ gap: 6, marginTop: 10 }}>
        <button className={`chip-btn ${d?.model === "perfect" ? "active" : ""}`} onClick={() => set("perfect")}>Perfect</button>
        <button className={`chip-btn ${d?.model === "realistic" ? "active" : ""}`} onClick={() => set("realistic")}>Realistic</button>
      </div>
      <p className="dim" style={{ fontSize: 11, marginTop: 6 }}>Realistic fills move the price against you (spread + slippage), and a small fraction of orders reject — paper P&L stops assuming perfect fills.</p>
    </Card>
  );
}
