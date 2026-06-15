import type { ActivityKind } from "../../types";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { activity } from "../../data/mock";

const KIND: Record<ActivityKind, { icon: string; tone: string }> = {
  "open-long": { icon: "up", tone: "pos" },
  "open-short": { icon: "down", tone: "neg" },
  "take-profit": { icon: "target", tone: "pos" },
  "stop-loss": { icon: "close", tone: "neg" },
  closed: { icon: "check", tone: "dim" },
};

export default function ActivityFeed() {
  return (
    <Card title="Bot Activity" subtitle="Live Feed" className="activity-card">
      <div className="activity-list">
        {activity.map((a) => {
          const k = KIND[a.kind];
          return (
            <div className="activity-item" key={a.id}>
              <span className={`activity-icon ${k.tone}`}>
                <Icon name={k.icon} size={15} />
              </span>
              <div className="activity-text">
                <b>{a.bot}</b>
                <span className="dim">{a.label}</span>
              </div>
              <span className="activity-time">{a.time}</span>
            </div>
          );
        })}
      </div>
      <button className="link-row" type="button">
        View All Logs <Icon name="chevron" size={14} />
      </button>
    </Card>
  );
}
