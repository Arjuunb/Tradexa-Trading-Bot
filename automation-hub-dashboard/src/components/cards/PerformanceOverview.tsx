import Card, { Dropdown } from "../common/Card";
import Sparkline from "../chart/Sparkline";
import { performance } from "../../data/mock";

export default function PerformanceOverview() {
  return (
    <Card title="Performance Overview" right={<Dropdown label="This Week" />} className="perf-card">
      <div className="perf-grid">
        {performance.map((p) => (
          <div className="perf-item" key={p.label}>
            <span className="perf-label">{p.label}</span>
            <div className="perf-value-row">
              <span className={`perf-value ${p.tone === "green" ? "pos" : p.tone === "red" ? "neg" : ""}`}>
                {p.value}
              </span>
              {p.spark && (
                <div className="perf-spark">
                  <Sparkline data={p.spark} color={p.sparkColor ?? "#8b5cf6"} height={24} />
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
