import Card from "../common/Card";
import Icon from "../common/Icon";
import { useApp } from "../../app-context";
import { useLive, hhmmss, type AlertRow } from "../../lib/api";

const kind = (sev: string) => {
  if (sev === "critical") return { icon: "warning", tone: "neg" };
  if (sev === "warning") return { icon: "warning", tone: "amber" };
  return { icon: "info", tone: "blue" };
};

export default function RecentAlerts() {
  const app = useApp();
  const { data } = useLive<AlertRow[]>("/ledger/alerts?limit=8", 4000);

  return (
    <Card title="Recent Alerts" className="alerts-card">
      <div className="alerts-list">
        {(data ?? []).map((a) => {
          const k = kind(a.severity);
          return (
            <div className="alert-item" key={a.id}>
              <span className={`alert-icon ${k.tone}`}><Icon name={k.icon} size={15} /></span>
              <div className="alert-text">
                <b>{a.title}</b>
                <span className="dim">{a.detail}</span>
              </div>
              <span className="alert-time">{hhmmss(a.ts)}</span>
            </div>
          );
        })}
        {(data?.length ?? 0) === 0 && <div className="empty-mini">No alerts yet.</div>}
      </div>
      <button className="link-row" type="button" onClick={() => app.go("Alerts")}>
        View All <Icon name="chevron" size={14} />
      </button>
    </Card>
  );
}
