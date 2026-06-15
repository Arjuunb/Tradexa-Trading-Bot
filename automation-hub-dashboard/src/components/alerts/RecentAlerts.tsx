import type { AlertKind } from "../../types";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { alerts } from "../../data/mock";

const KIND: Record<AlertKind, { icon: string; tone: string }> = {
  warning: { icon: "warning", tone: "amber" },
  success: { icon: "check", tone: "pos" },
  info: { icon: "info", tone: "blue" },
  error: { icon: "close", tone: "neg" },
};

export default function RecentAlerts() {
  return (
    <Card title="Recent Alerts" className="alerts-card">
      <div className="alerts-list">
        {alerts.map((a) => {
          const k = KIND[a.kind];
          return (
            <div className="alert-item" key={a.id}>
              <span className={`alert-icon ${k.tone}`}>
                <Icon name={k.icon} size={15} />
              </span>
              <div className="alert-text">
                <b>{a.title}</b>
                <span className="dim">{a.detail}</span>
              </div>
              <span className="alert-time">{a.time}</span>
            </div>
          );
        })}
      </div>
      <button className="link-row" type="button">
        View All <Icon name="chevron" size={14} />
      </button>
    </Card>
  );
}
