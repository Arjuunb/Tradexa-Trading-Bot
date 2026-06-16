import Icon from "../common/Icon";
import { useApp } from "../../app-context";
import { useLive, type SystemStatus } from "../../lib/api";

interface TopHeaderProps {
  onToggleSidebar: () => void;
  title?: string;
}

export default function TopHeader({ onToggleSidebar, title = "Dashboard" }: TopHeaderProps) {
  const app = useApp();
  const { data, error } = useLive<SystemStatus>("/system/status", 4000);

  let dot = "offline", label = "Backend offline", detail = "start the API";
  if (data) {
    if (data.auto_halted) { dot = "warn"; label = "Auto-halted"; detail = data.halt_reason || "drawdown breaker"; }
    else if (data.engine_running) { dot = "online"; label = "Paper · Engine running"; detail = `${data.strategy} · ${data.timeframe}`; }
    else { dot = "warn"; label = "Paper · Engine stopped"; detail = data.trading_state; }
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button className="icon-btn" onClick={onToggleSidebar} aria-label="Toggle menu">
          <Icon name="menu" size={20} />
        </button>
        <h1 className="page-title">{title}</h1>
      </div>

      <div className="status-pill" title={error ? "Backend not reachable" : detail}>
        <span className={`dot ${dot}`} />
        <b>{label}</b>
        <span className="sep">·</span>
        <span className="dim">{detail}</span>
      </div>

      <div className="topbar-right">
        <button className="icon-btn" aria-label="Alerts" onClick={() => app.go("Alerts")}>
          <Icon name="bell" size={18} />
        </button>
        <button className="icon-btn" aria-label="Settings" onClick={() => app.go("Settings")}>
          <Icon name="help" size={18} />
        </button>
        <div className="profile">
          <div className="avatar">PA</div>
          <div className="profile-meta">
            <b>Paper Account</b>
            <span className="dim">Simulation</span>
          </div>
        </div>
      </div>
    </header>
  );
}
