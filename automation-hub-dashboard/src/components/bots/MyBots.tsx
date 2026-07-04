import { useMemo, useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { statusColor } from "../../theme";
import { useApp } from "../../app-context";
import { useLive, type LiveBot } from "../../lib/api";

type Tab = "All" | "Running" | "Paused" | "Stopped";

const money = (n: number) => (n === 0 ? "$0.00" : `${n > 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}`);

// Real bots = the engine's symbols, live from /bots/live.
export default function MyBots() {
  const app = useApp();
  const [tab, setTab] = useState<Tab>("All");
  const { data } = useLive<LiveBot[]>("/bots/live", 2500);
  const bots = Array.isArray(data) ? data : [];

  const counts = useMemo(() => ({
    All: bots.length,
    Running: bots.filter((b) => b.status === "Running").length,
    Paused: bots.filter((b) => b.status === "Paused").length,
    Stopped: bots.filter((b) => b.status === "Stopped").length,
  }), [bots]);

  const visible = bots.filter((b) => (tab === "All" ? true : b.status === tab));
  const tabs: Tab[] = ["All", "Running", "Paused", "Stopped"];

  return (
    <Card title="My Bots" subtitle="paper" className="bots-card">
      <div className="tabs">
        {tabs.map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)} type="button">
            {t} <span className="tab-count">({counts[t]})</span>
          </button>
        ))}
      </div>

      <div className="bot-list">
        {visible.map((b) => (
          <div className="bot-row" key={b.id} style={{ ["--bot-accent" as any]: statusColor(b.status) }}>
            <div className="bot-avatar" style={{ background: `${statusColor(b.status)}22`, color: statusColor(b.status) }}>
              {b.symbol.replace("USDT", "").slice(0, 3)}
            </div>
            <div className="bot-info bot-info-link" onClick={() => app.viewBot(b.id)} title="View details">
              <div className="bot-name-row">
                <b>{b.symbol}</b>
                <span className="status-tag" style={{ background: `${statusColor(b.status)}22`, color: statusColor(b.status) }}>{b.status}</span>
                {b.open && (
                  <span className="status-tag" style={{ background: b.side === "long" ? "#22c55e22" : "#ef444422", color: b.side === "long" ? "var(--green)" : "var(--red)" }}>
                    {b.side} {b.size.toFixed(3)}
                  </span>
                )}
              </div>
              <span className="bot-meta">{b.strategy} · {b.timeframe} · {b.num_trades} trades · {Math.round((b.win_rate ?? 0) * 100)}% win</span>
            </div>
            <div className="bot-pnl">
              <span className="bot-pnl-label">Realized</span>
              <span className={b.realized_pnl > 0 ? "pos" : b.realized_pnl < 0 ? "neg" : "dim"}>{money(b.realized_pnl)}</span>
            </div>
            <button className="icon-btn sm" title="View details" onClick={() => app.viewBot(b.id)}><Icon name="chart" size={14} /></button>
          </div>
        ))}
        {visible.length === 0 && <div className="empty-mini">No bots in this view.</div>}
      </div>

      <button className="link-row" type="button" onClick={() => app.go("Bots")}>
        View All Bots <Icon name="chevron" size={14} />
      </button>
    </Card>
  );
}
