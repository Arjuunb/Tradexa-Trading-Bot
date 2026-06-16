import Icon from "../common/Icon";
import { useLive, type EngineStatus, type PaperAccount } from "../../lib/api";

const money = (n: number | undefined) => `${(n ?? 0) >= 0 ? "+" : "-"}$${Math.abs(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export default function MetricCards() {
  const engine = useLive<EngineStatus>("/engine/status", 2000);
  const account = useLive<PaperAccount>("/paper/account", 2000);
  const e = engine.data;
  const a = account.data;

  const cards = [
    { key: "engine", label: "Engine", value: e?.running ? "Running" : "Stopped", sub: e ? `${e.symbols.length} symbols · ${e.timeframe}` : "—", color: e?.running ? "#22c55e" : "#ef4444", tone: e?.running ? "green" : "" },
    { key: "open", label: "Open Positions", value: String(a?.open_positions ?? 0), sub: "live", color: "#3b82f6", tone: "" },
    { key: "signals", label: "Signals", value: String(e?.signals ?? 0), sub: `${e?.trades ?? 0} fills`, color: "#8b5cf6", tone: "" },
    { key: "rejections", label: "Rejections", value: String(e?.rejections ?? 0), sub: "risk-blocked", color: "#f59e0b", tone: "" },
  ];

  const realized = a?.realized_pnl ?? 0;

  return (
    <div className="metric-row">
      {cards.map((m) => (
        <div className="metric-card" key={m.key}>
          <div className="metric-top">
            <span className="metric-label">{m.label}</span>
            <span className="metric-icon" style={{ color: m.color }}><Icon name="robot" size={16} /></span>
          </div>
          <div className="metric-main">
            <span className="metric-value">{m.value}</span>
            <span className={`metric-sub ${m.tone === "green" ? "pos" : ""}`}>{m.sub}</span>
          </div>
        </div>
      ))}

      <div className="metric-card pnl-card">
        <div className="metric-top">
          <span className="metric-label">Realized P&amp;L</span>
          <span className={`metric-icon ${realized >= 0 ? "pos" : "neg"}`}><Icon name="chart" size={16} /></span>
        </div>
        <div className="metric-main">
          <span className={`metric-value ${realized >= 0 ? "pos" : "neg"}`}>{money(realized)}</span>
        </div>
        <span className="metric-sub dim">Balance ${(a?.balance ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
      </div>
    </div>
  );
}
