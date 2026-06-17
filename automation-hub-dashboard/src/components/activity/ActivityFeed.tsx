import Card from "../common/Card";
import Icon from "../common/Icon";
import { useApp } from "../../app-context";
import { useLive, hhmmss, type LogRow } from "../../lib/api";

const tone = (l: LogRow) => {
  if (l.level === "error") return { icon: "warning", tone: "neg" };
  if (l.level === "warning") return { icon: "close", tone: "neg" };
  if (l.stage === "execution") return { icon: "check", tone: "pos" };
  return { icon: "info", tone: "dim" };
};

export default function ActivityFeed() {
  const app = useApp();
  const { data } = useLive<LogRow[]>("/ledger/logs?limit=12", 2500);

  return (
    <Card title="Bot Activity" subtitle="Live Feed" className="activity-card">
      <div className="activity-list">
        {(data ?? []).map((a) => {
          const k = tone(a);
          return (
            <div className="activity-item" key={a.id}>
              <span className={`activity-icon ${k.tone}`}><Icon name={k.icon} size={15} /></span>
              <div className="activity-text">
                <b>{a.symbol || a.stage}</b>
                <span className="dim">{a.message}</span>
              </div>
              <span className="activity-time">{hhmmss(a.ts)}</span>
            </div>
          );
        })}
        {(data?.length ?? 0) === 0 && <div className="empty-mini">No activity yet.</div>}
      </div>
      <button className="link-row" type="button" onClick={() => app.go("Logs")}>
        View All Logs <Icon name="chevron" size={14} />
      </button>
    </Card>
  );
}
