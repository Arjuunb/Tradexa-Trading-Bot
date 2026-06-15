import type { BotHealth } from "../../types";
import Card from "../common/Card";

const GOOD = ["Running", "Connected", "Live"];

interface Item { label: string; val: string; ok?: boolean; warn?: boolean; }

export default function BotHealthPanel({ h }: { h: BotHealth }) {
  const items: Item[] = [
    { label: "Bot status", val: h.status, ok: GOOD.includes(h.status), warn: h.status === "Paused" },
    { label: "Exchange", val: h.exchange, ok: GOOD.includes(h.exchange) },
    { label: "Data feed", val: h.dataFeed, ok: h.dataFeed === "Live", warn: h.dataFeed === "Delayed" },
    { label: "Last heartbeat", val: h.heartbeat },
    { label: "Uptime", val: h.uptime },
    { label: "Last scan", val: h.lastScan },
    { label: "Last trade", val: h.lastTrade },
    { label: "Error count", val: String(h.errors), ok: h.errors === 0, warn: h.errors > 0 },
  ];
  return (
    <Card title="Bot Health" subtitle="Priority 4 · self-monitoring">
      <div className="health-grid">
        {items.map((it) => (
          <div className="health-item" key={it.label}>
            <span className="dim">{it.label}</span>
            <b>
              {it.ok !== undefined && (
                <span className={`dot ${it.ok ? "online" : it.warn ? "warndot" : "offdot"}`} />
              )}
              {it.val}
            </b>
          </div>
        ))}
      </div>
    </Card>
  );
}
