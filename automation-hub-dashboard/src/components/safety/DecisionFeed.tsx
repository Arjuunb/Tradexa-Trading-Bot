import type { Decision, Verdict } from "../../types";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import { decisions } from "../../data/mock";

const vTone = (v: Verdict): "green" | "red" | "amber" =>
  v === "Allowed" ? "green" : v === "Blocked" ? "red" : "amber";
const sigTone = (s: string): "green" | "red" | "default" =>
  s === "Buy" ? "green" : s === "Sell" ? "red" : "default";

export default function DecisionFeed({ items = decisions }: { items?: Decision[] }) {
  if (!items.length) return <div className="empty-state">No decisions recorded yet.</div>;
  return (
    <div className="decision-list">
      {items.map((d) => (
        <div className={`decision-card v-${vTone(d.verdict)}`} key={d.id}>
          <div className="decision-head">
            <span className="decision-time mono">{d.time}</span>
            <b>{d.symbol}</b>
            <span className="dim">{d.strategy}</span>
            <span className="decision-spacer" />
            <Badge text={`${d.signal} · ${d.confidence}%`} tone={sigTone(d.signal)} />
          </div>
          <ul className="checks">
            {d.checks.map((c, i) => (
              <li key={i} className={c.passed ? "pass" : "fail"}>
                <Icon name={c.passed ? "check" : "close"} size={13} /> {c.rule}
              </li>
            ))}
          </ul>
          <div className={`verdict ${vTone(d.verdict)}`}>
            <Badge text={d.verdict} tone={vTone(d.verdict)} />
            <span>{d.reason}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
