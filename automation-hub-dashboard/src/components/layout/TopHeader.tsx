import Icon from "../common/Icon";
import HeaderControls from "./HeaderControls";
import { useApp } from "../../app-context";

interface TopHeaderProps {
  onToggleSidebar: () => void;
  title?: string;
}

export default function TopHeader({ onToggleSidebar, title = "Dashboard" }: TopHeaderProps) {
  const app = useApp();

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button className="icon-btn" onClick={onToggleSidebar} aria-label="Toggle menu">
          <Icon name="menu" size={20} />
        </button>
        <h1 className="page-title">{title}</h1>
      </div>

      {/* Interactive control strip: mode · engine · strategy · timeframe · ⚙ —
          each segment opens an anchored popover that drives the real engine. */}
      <HeaderControls />

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
