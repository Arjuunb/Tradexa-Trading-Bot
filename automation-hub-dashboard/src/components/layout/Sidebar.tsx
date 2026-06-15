import Icon, { NAV_ICON } from "../common/Icon";
import { NAV_ITEMS, account } from "../../data/mock";

interface SidebarProps {
  active: string;
  onSelect: (item: string) => void;
  collapsed?: boolean;
}

export default function Sidebar({ active, onSelect, collapsed }: SidebarProps) {
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="brand">
        <span className="brand-mark">A</span>
        <span className="brand-name">Automation Hub</span>
      </div>

      <nav className="nav">
        {NAV_ITEMS.map((item) => (
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
        <div className="account-title">Account Summary</div>
        <div className="account-equity">{account.equity}</div>
        <div className="account-row">
          <span>Available Balance</span>
          <b>{account.available}</b>
        </div>
        <div className="account-row">
          <span>Daily P&amp;L</span>
          <b className="pos">{account.dailyPnl}</b>
        </div>
        <div className="account-row">
          <span>Open Positions</span>
          <b>{account.openPositions}</b>
        </div>
        <div className="account-row">
          <span>Exposure</span>
          <b>{account.exposure}</b>
        </div>
        <button className="btn btn-soft full" type="button" onClick={() => onSelect("Analytics")}>View Details</button>
      </div>

      <div className="market-status">
        <span className="dot online" /> Market Status: <b className="pos">Connected</b>
      </div>
    </aside>
  );
}
