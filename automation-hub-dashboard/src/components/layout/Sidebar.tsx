import Icon, { NAV_ICON } from "../common/Icon";
import Logo from "../common/Logo";
import { NAV_LABELS } from "../../app-context";
import { useLive, type RiskSummary } from "../../lib/api";

interface SidebarProps {
  active: string;
  onSelect: (item: string) => void;
  collapsed?: boolean;
}

const money = (n: number | undefined) => `$${(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export default function Sidebar({ active, onSelect, collapsed }: SidebarProps) {
  const { data: r } = useLive<RiskSummary>("/risk/summary", 3000);

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="brand">
        <span className="brand-mark"><Logo size={30} /></span>
        <span className="brand-name">Automation Hub</span>
      </div>

      <nav className="nav">
        {NAV_LABELS.map((item) => (
          <button
            key={item}
            className={`nav-item ${active === item ? "active" : ""}`}
            onClick={() => onSelect(item)}
            type="button"
          >
            <Icon name={NAV_ICON[item] ?? "grid"} size={18} />
            <span>{item}</span>
          </button>
        ))}
      </nav>

      <div className="account-card">
        <div className="account-title">Paper Account</div>
        <div className="account-equity">{r ? money(r.equity) : "—"}</div>
        <div className="account-row"><span>Realized P&amp;L</span>
          <b className={(r?.realized_pnl ?? 0) >= 0 ? "pos" : "neg"}>{r ? money(r.realized_pnl) : "—"}</b></div>
        <div className="account-row"><span>Open Positions</span><b>{r?.open_positions ?? 0}</b></div>
        <div className="account-row"><span>Exposure</span><b>{r ? `${(r.exposure_pct * 100).toFixed(1)}%` : "—"}</b></div>
        <button className="btn btn-soft full" type="button" onClick={() => onSelect("Backtesting")}>Performance</button>
      </div>

      <div className="market-status">
        <span className={`dot ${r ? "warn" : "offline"}`} /> Mode: <b>Paper (simulation)</b>
      </div>
    </aside>
  );
}
