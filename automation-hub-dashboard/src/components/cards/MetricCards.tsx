import Icon from "../common/Icon";
import Sparkline from "../chart/Sparkline";
import { useLive, type EngineStatus, type EquityCurveData, type PaperAccount } from "../../lib/api";

const money = (n: number | undefined) => `${(n ?? 0) >= 0 ? "+" : "-"}$${Math.abs(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export default function MetricCards() {
  const engine = useLive<EngineStatus>("/engine/status", 2000);
  const account = useLive<PaperAccount>("/paper/account", 2000);
  const eq = useLive<EquityCurveData>("/paper/equity-curve", 4000);
  const e = engine.data;
  const a = account.data;
  const curve = (eq.data?.points ?? []).map((p) => p.equity);

  const cards = [
    { key: "engine", label: "Engine", value: e?.running ? "Running" : "Stopped", sub: e ? `${e.symbols.length} symbols · ${e.timeframe}` : "—", color: e?.running ? "#22c55e" : "#ef4444", icon: "bot", tone: e?.running ? "green" : "" },
    { key: "open", label: "Open Positions", value: String(a?.open_positions ?? 0), sub: "live", color: "#3b82f6", icon: "layers", tone: "" },
    { key: "signals", label: "Signals", value: String(e?.signals ?? 0), sub: `${e?.trades ?? 0} fills`, color: "#eab54f", icon: "target", tone: "" },
    { key: "rejections", label: "Rejections", value: String(e?.rejections ?? 0), sub: "risk-blocked", color: "#eab54f", icon: "shield", tone: "" },
  ];

  const realized = a?.realized_pnl ?? 0;

  return (
    <div className="metric-row">
      {cards.map((m) => (
        <div className="metric-card" key={m.key}>
          <span className="metric-accent" style={{ background: m.color }} />
          <div className="metric-top">
            <span className="metric-label">{m.label}</span>
            <span className="metric-icon" style={{ background: m.color + "22", color: m.color }}><Icon name={m.icon} size={16} /></span>
          </div>
          <div className="metric-main">
            <span className="metric-value">{m.value}</span>
            <span className={`metric-sub ${m.tone === "green" ? "pos" : ""}`}>{m.sub}</span>
          </div>
        </div>
      ))}

      <div className="metric-card pnl-card">
        <span className="metric-accent" style={{ background: realized >= 0 ? "#22c55e" : "#ef4444" }} />
        <div className="metric-top">
          <span className="metric-label">Realized P&amp;L</span>
          <span className={`metric-icon ${realized >= 0 ? "pos" : "neg"}`}><Icon name="chart" size={16} /></span>
        </div>
        <div className="metric-main">
          <span className={`metric-value ${realized >= 0 ? "pos" : "neg"}`}>{money(realized)}</span>
        </div>
        {curve.length > 1 ? (
          <div className="metric-spark"><Sparkline data={curve} color={realized >= 0 ? "#22c55e" : "#ef4444"} height={34} /></div>
        ) : (
          <span className="metric-sub dim">Balance ${(a?.balance ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
        )}
      </div>
    </div>
  );
}
