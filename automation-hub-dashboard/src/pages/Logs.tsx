import { useMemo, useState } from "react";
import type { LogType } from "../types";
import Icon from "../components/common/Icon";
import { Badge, PageHeader } from "../components/common/ui";
import { logs as seedLogs } from "../data/mock";

const FILTERS: (LogType | "All")[] = ["All", "Info", "Warning", "Error", "Trade", "Risk"];
const tone = (t: LogType) =>
  ({ Info: "blue", Warning: "amber", Error: "red", Trade: "green", Risk: "purple" }[t] as any);

export default function LogsPage() {
  const [items, setItems] = useState(seedLogs);
  const [filter, setFilter] = useState<LogType | "All">("All");
  const [query, setQuery] = useState("");

  const visible = useMemo(
    () => items.filter((l) => (filter === "All" || l.type === filter) && (l.message.toLowerCase().includes(query.toLowerCase()) || l.bot.toLowerCase().includes(query.toLowerCase()))),
    [items, filter, query],
  );

  return (
    <>
      <PageHeader
        title="Logs"
        subtitle={`${items.length} log entries`}
        actions={
          <div className="row-actions">
            <button className="btn btn-ghost" onClick={() => setItems([])}><Icon name="close" size={14} /> Clear</button>
            <button className="btn btn-soft"><Icon name="external" size={14} /> Export</button>
          </div>
        }
      />

      <div className="toolbar">
        <div className="search">
          <Icon name="info" size={15} className="search-icon" />
          <input placeholder="Search logs…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="chips">
          {FILTERS.map((f) => (
            <button key={f} className={`chip-btn ${filter === f ? "active" : ""}`} onClick={() => setFilter(f)}>{f}</button>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Time</th><th>Bot</th><th>Type</th><th>Message</th><th>Status</th></tr></thead>
            <tbody>
              {visible.map((l) => (
                <tr key={l.id}>
                  <td className="dim mono">{l.time}</td>
                  <td>{l.bot}</td>
                  <td><Badge text={l.type} tone={tone(l.type)} /></td>
                  <td>{l.message}</td>
                  <td className="dim">{l.status}</td>
                </tr>
              ))}
              {visible.length === 0 && <tr><td colSpan={5} className="dim ta-center" style={{ padding: 24 }}>No logs to show.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
