import Logo from "../common/Logo";
import {
  LayoutDashboard, CandlestickChart, Layers, FlaskConical, RefreshCw, PlayCircle,
  NotebookPen, Rocket, Wallet, BarChart3, Bot, ShieldAlert, Brain, ScrollText,
  BookOpen, Settings, Lock, type LucideIcon,
} from "lucide-react";
import { NAV_LABELS } from "../../app-context";
import { useLive, type RiskSummary } from "../../lib/api";

// Real icons (lucide), one per page — gold when active, sky on hover.
const NAV_LUCIDE: Record<string, LucideIcon> = {
  Overview: LayoutDashboard,
  Markets: CandlestickChart,
  Strategies: Layers,
  Backtesting: FlaskConical,
  Simulation: RefreshCw,
  Replay: PlayCircle,
  "Paper Trading": NotebookPen,
  "Live Trading": Rocket,
  Portfolio: Wallet,
  Analytics: BarChart3,
  "AI Assistant": Bot,
  "Risk Manager": ShieldAlert,
  Evolution: Brain,
  Journal: BookOpen,
  Logs: ScrollText,
  Settings: Settings,
  "Safety Center": Lock,
};

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
        {NAV_LABELS.map((item) => {
          const NavIcon = NAV_LUCIDE[item] ?? LayoutDashboard;
          return (
            <button
              key={item}
              className={`nav-item ${active === item ? "active" : ""}`}
              onClick={() => onSelect(item)}
              type="button"
            >
              <NavIcon size={18} strokeWidth={1.9} className="nav-ico" aria-hidden />
              <span>{item}</span>
            </button>
          );
        })}
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
