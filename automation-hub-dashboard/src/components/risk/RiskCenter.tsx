import Card from "../common/Card";
import Icon from "../common/Icon";
import ProgressBar from "../common/ProgressBar";
import { riskMetrics } from "../../data/mock";

export default function RiskCenter() {
  return (
    <Card title="Risk Center" className="risk-card">
      <div className="risk-list">
        {riskMetrics.map((r) => (
          <div className="risk-item" key={r.label}>
            <div className="risk-head">
              <span className="dim">{r.label}</span>
              <b>{r.value}</b>
            </div>
            <ProgressBar pct={r.pct} tone={r.tone} />
            <span className="risk-pct">{r.pct}%</span>
          </div>
        ))}
      </div>
      <button className="link-row" type="button">
        View Full Risk <Icon name="chevron" size={14} />
      </button>
    </Card>
  );
}
