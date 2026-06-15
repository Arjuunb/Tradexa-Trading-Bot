import type { GuardStatus } from "../../types";
import Card from "../common/Card";
import ProgressBar from "../common/ProgressBar";
import { Badge } from "../common/ui";
import { capitalGuards, tradingStatus } from "../../data/mock";

const tone = (s: GuardStatus): "green" | "amber" | "red" =>
  s === "OK" ? "green" : s === "Warning" ? "amber" : "red";

export default function CapitalProtection() {
  const active = tradingStatus.state === "Active";
  return (
    <Card title="Capital Protection" subtitle="Priority 1 · mandatory limits">
      <div className={`trading-status ${active ? "ok" : "warn"}`}>
        <span className={`dot ${active ? "online" : "warndot"}`} />
        <div>
          <b>Trading: {tradingStatus.state}</b>
          <span className="dim">{tradingStatus.detail}</span>
        </div>
      </div>
      <div className="guard-list">
        {capitalGuards.map((g) => (
          <div className="guard-item" key={g.rule}>
            <div className="guard-head">
              <span className="dim">{g.rule}</span>
              <span className="guard-val">
                <b>{g.value}</b> <span className="dim">/ {g.limit}</span>
                <Badge text={g.status} tone={tone(g.status)} />
              </span>
            </div>
            <ProgressBar pct={g.pct} tone={tone(g.status)} />
          </div>
        ))}
      </div>
    </Card>
  );
}
