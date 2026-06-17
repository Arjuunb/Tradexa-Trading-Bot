import { useMemo, useState } from "react";
import Icon from "../components/common/Icon";
import { Badge, PageHeader } from "../components/common/ui";
import { useLive, hhmmss, API_BASE, type LogRow } from "../lib/api";

const LEVELS = ["All", "info", "warning", "error"] as const;
const tone = (l: string) => ({ info: "blue", warning: "amber", error: "red" }[l] as any) ?? "default";

export default function LogsPage() {
  const { data, error, loading } = useLive<LogRow[]>("/ledger/logs?limit=300", 2500);
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("All");
  const [query, setQuery] = useState("");

  const items = data ?? [];
  const visible = useMemo(
    () => items.filter((l) =>
      (level === "All" || l.level === level) &&
      (l.message.toLowerCase().includes(query.toLowerCase()) || (l.symbol ?? "").toLowerCase().includes(query.toLowerCase()))),
    [items, level, query],
  );

  return (
    <>
      <PageHeader title="Decision Log" subtitle={`${items.length} entries · live from the engine pipeline`}
        actions={
          <div className="row-actions">
            <a className="btn btn-soft" href={`${API_BASE}/ledger/logs/export?fmt=csv`} target="_blank" rel="noreferrer"><Icon name="external" size={14} /> CSV</a>
            <a className="btn btn-soft" href={`${API_BASE}/ledger/logs/export?fmt=json`} target="_blank" rel="noreferrer"><Icon name="external" size={14} /> JSON</a>
          </div>
        } />

      {error && !data && (
        <div className="card" style={{ borderColor: "#ef4444" }}>
          <Icon name="warning" size={15} className="neg" /> Backend not reachable. Start the API to stream live logs.
        </div>
      )}

      <div className="toolbar">
        <div className="search">
          <Icon name="info" size={15} className="search-icon" />
          <input placeholder="Search messages / symbols…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="chips">
          {LEVELS.map((f) => (
            <button key={f} className={`chip-btn ${level === f ? "active" : ""}`} onClick={() => setLevel(f)}>{f}</button>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Time</th><th>Level</th><th>Stage</th><th>Symbol</th><th>Message</th></tr></thead>
            <tbody>
              {visible.map((l) => (
                <tr key={l.id}>
                  <td className="dim mono">{hhmmss(l.ts)}</td>
                  <td><Badge text={l.level} tone={tone(l.level)} /></td>
                  <td className="dim">{l.stage}</td>
                  <td>{l.symbol}</td>
                  <td>{l.message}</td>
                </tr>
              ))}
              {visible.length === 0 && (
                <tr><td colSpan={5} className="dim ta-center" style={{ padding: 24 }}>{loading ? "Loading…" : "No logs to show."}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
