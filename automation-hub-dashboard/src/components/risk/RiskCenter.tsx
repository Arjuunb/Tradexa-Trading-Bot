import Card from "../common/Card";
import Icon from "../common/Icon";
import ProgressBar from "../common/ProgressBar";
import { useApp } from "../../app-context";
import { useLive, type RiskSummary } from "../../lib/api";

export default function RiskCenter() {
  const app = useApp();
  const { data: r } = useLive<RiskSummary>("/risk/summary", 2500);

  const expUse = r && r.exposure_limit_pct > 0 ? Math.min(100, (r.exposure_pct / r.exposure_limit_pct) * 100) : 0;
  const posUse = r && r.max_open_positions > 0 ? Math.min(100, (r.open_positions / r.max_open_positions) * 100) : 0;
  const tone = (u: number) => (u >= 90 ? "red" : u >= 60 ? "amber" : "green") as "red" | "amber" | "green";

  const metrics = [
    { label: "Exposure", value: r ? `${(r.exposure_pct * 100).toFixed(1)}% / ${(r.exposure_limit_pct * 100).toFixed(0)}%` : "—", pct: Math.round(expUse), tone: tone(expUse) },
    { label: "Open Positions", value: r ? `${r.open_positions} / ${r.max_open_positions}` : "—", pct: Math.round(posUse), tone: tone(posUse) },
    { label: "Risk-blocked", value: r ? String(r.rejections) : "—", pct: 0, tone: "green" as const },
    { label: "Trading state", value: r?.trading_state ?? "—", pct: r?.trading_state === "Active" ? 100 : 0, tone: (r?.trading_state === "Active" ? "green" : "red") as "green" | "red" },
  ];

  return (
    <Card title="Risk Center" subtitle="live" className="risk-card">
      <div className="risk-list">
        {metrics.map((m) => (
          <div className="risk-item" key={m.label}>
            <div className="risk-head"><span className="dim">{m.label}</span><b>{m.value}</b></div>
            <ProgressBar pct={m.pct} tone={m.tone} />
            <span className="risk-pct">{m.pct}%</span>
          </div>
        ))}
      </div>
      <button className="link-row" type="button" onClick={() => app.go("Risk Center")}>
        View Full Risk <Icon name="chevron" size={14} />
      </button>
    </Card>
  );
}
