import Logo from "../common/Logo";
import {
  LayoutDashboard, CandlestickChart, Search, Layers, FlaskConical, RefreshCw, PlayCircle,
  NotebookPen, Rocket, Wallet, BarChart3, Bot, ShieldAlert, Brain, ScrollText,
  BookOpen, Activity, BadgeCheck, Settings, Lock, BrainCircuit, Gauge, Blocks, SquareTerminal, ListChecks, LayoutGrid, SlidersHorizontal, type LucideIcon,
} from "lucide-react";
import { NAV_GROUPS } from "../../app-context";
import { useLive, type RiskSummary, type PaperAccount } from "../../lib/api";
import { signedMoney } from "../../lib/format";

// Real icons (lucide), one per page — gold when active, sky on hover.
const NAV_LUCIDE: Record<string, LucideIcon> = {
  Dashboard: LayoutDashboard,
  Markets: CandlestickChart,
  Symbols: Search,
  Strategies: Layers,
  Backtesting: FlaskConical,
  "Optimization Lab": SlidersHorizontal,
  Simulation: RefreshCw,
  Replay: PlayCircle,
  "Paper Trading": SquareTerminal,   // the Bot Observation Terminal
  "Paper Account": NotebookPen,
  "Live Trading": Rocket,
  Portfolio: Wallet,
  Analytics: BarChart3,
  "Strategy Proof": BadgeCheck,
  "Strategy Studio": Blocks,
  "Grid & DCA": LayoutGrid,
  "AI Intelligence": Gauge,
  "AI Assistant": Bot,
  "Risk Manager": ShieldAlert,
  Evolution: Brain,
  Journal: BookOpen,
  "Decision Archive": ListChecks,
  Memory: BrainCircuit,
  "Bot Health": Activity,
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
  const { data: acct } = useLive<PaperAccount>("/paper/account", 3000);

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <a
        className="brand"
        href={(import.meta.env.VITE_LANDING_URL as string | undefined) || "/"}
        title="Back to TradeLogX Nexus home"
      >
        <span className="brand-mark"><Logo size={30} /></span>
        <span className="brand-name">
          TradeLogX
          <span className="brand-sub">Nexus</span>
        </span>
      </a>

      <nav className="nav">
        {NAV_GROUPS.map((group, gi) => (
          <div className="nav-group" key={group.title ?? gi}>
            {group.title && <div className="nav-group-title">{group.title}</div>}
            {group.items.map((item) => {
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
          </div>
        ))}
      </nav>

      <div className="account-card">
        <div className="account-title">Current Equity</div>
        <div className="account-equity">{acct ? money(acct.current_equity) : r ? money(r.equity) : "—"}</div>
        <div className="account-row"><span>Initial capital</span><b>{acct ? money(acct.initial_capital) : "—"}</b></div>
        <div className="account-row"><span>Realized P&amp;L</span>
          <b className={(r?.realized_pnl ?? 0) >= 0 ? "pos" : "neg"}>{r ? signedMoney(r.realized_pnl) : "—"}</b></div>
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
