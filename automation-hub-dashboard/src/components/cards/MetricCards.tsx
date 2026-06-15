import Sparkline from "../chart/Sparkline";
import Icon from "../common/Icon";
import { metricCards, totalPnl } from "../../data/mock";

export default function MetricCards() {
  return (
    <div className="metric-row">
      {metricCards.map((m) => (
        <div className="metric-card" key={m.key}>
          <div className="metric-top">
            <span className="metric-label">{m.label}</span>
            <span className="metric-icon" style={{ color: m.color }}>
              <Icon name="robot" size={16} />
            </span>
          </div>
          <div className="metric-main">
            <span className="metric-value">{m.value}</span>
            <span className={`metric-sub ${m.tone === "green" ? "pos" : ""}`}>{m.sub}</span>
          </div>
          {m.key !== "total" && (
            <div className="metric-spark">
              <Sparkline data={m.spark} color={m.color} height={34} />
            </div>
          )}
        </div>
      ))}

      <div className="metric-card pnl-card">
        <div className="metric-top">
          <span className="metric-label">Total P&amp;L (All Time)</span>
          <span className="metric-icon pos">
            <Icon name="chart" size={16} />
          </span>
        </div>
        <div className="metric-main">
          <span className="metric-value pos">{totalPnl.value}</span>
        </div>
        <span className="metric-sub pos">{totalPnl.pct}</span>
      </div>
    </div>
  );
}
