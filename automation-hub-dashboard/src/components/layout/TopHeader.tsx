import Icon from "../common/Icon";
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

      <div className="status-pill">
        <span className="dot online" />
        <b>Live</b>
        <span className="sep">·</span>
        <span className="dim">All Systems Operational</span>
      </div>

      <div className="topbar-right">
        <button className="icon-btn" aria-label="Notifications" onClick={() => app.go("Alerts")}>
          <Icon name="bell" size={18} />
          <span className="badge-dot" />
        </button>
        <button className="icon-btn" aria-label="Help" onClick={() => app.go("Settings")}>
          <Icon name="help" size={18} />
        </button>
        <button className="icon-btn" aria-label="Toggle theme">
          <Icon name="theme" size={18} />
        </button>
        <div className="profile">
          <div className="avatar">AT</div>
          <div className="profile-meta">
            <b>Alex Trader</b>
            <span className="dim">Pro Plan</span>
          </div>
        </div>
      </div>
    </header>
  );
}
