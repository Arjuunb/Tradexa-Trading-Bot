import { useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { PageHeader } from "../components/common/ui";
import { useLive, type BotSettings, type PaperTradeRow, type SystemStatus, type BrokerList } from "../lib/api";
import { Badge } from "../components/common/ui";
import { getProgress } from "../lib/progress";

function riskValid(s: BotSettings | null): boolean {
  if (!s) return false;
  const e = s.editable;
  return e.risk_per_trade_pct > 0 && e.risk_per_trade_pct <= 0.05
    && e.max_drawdown_pct > 0 && e.max_open_positions >= 1;
}

export default function LiveTradingPage() {
  const { data: sys } = useLive<SystemStatus>("/system/status", 3000);
  const { data: settings } = useLive<BotSettings>("/settings", 5000);
  const { data: trades } = useLive<PaperTradeRow[]>("/paper/trades", 4000);
  const [confirmed, setConfirmed] = useState(false);

  const prog = getProgress();
  const brokerConnected = !!(sys?.broker_connected ?? settings?.readonly.broker_connected);
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
      <PageHeader title="Live Trading" subtitle="Locked until the full safety flow passes and a broker is connected" />

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

      <BrokerConnections />
    </>
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
            {b.brokers.map((br) => (
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
