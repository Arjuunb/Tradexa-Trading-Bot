import { Fragment, useMemo, useState } from "react";
import { usePref } from "../lib/prefs";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { Badge, PageHeader } from "../components/common/ui";
import { useLive, hhmmss, API_BASE, type LogRow, type Readiness, type BotOsSnap } from "../lib/api";

type SkippedTrade = {
  id: number; ts: string; symbol: string; side: string; stage: string;
  status: string; reason: string; entry: number | null; stop: number | null;
  target: number | null; strategy: string; timeframe: string; category: string;
  snapshot: Record<string, any>;
};

const catTone = (c: string) =>
  ({ risk: "red", safety: "red", quality: "amber", duplicate: "blue",
     session: "blue", signal: "default" }[c] as any) ?? "default";

function SkippedTrades() {
  const [q, setQ] = useState("");
  const [stage, setStage] = usePref<string>("logs.stage", "all");
  const [open, setOpen] = useState<number | null>(null);
  const qs = new URLSearchParams({ limit: "200" });
  if (q.trim()) qs.set("q", q.trim());
  if (stage !== "all") qs.set("stage", stage);
  const rows = useLive<{ trades: SkippedTrade[] }>(`/skipped/trades?${qs.toString()}`, 4000);
  const summary = useLive<{ stages: { stage: string; count: number }[] }>("/skipped/summary", 8000);

  const trades = rows.data?.trades ?? [];
  const stages = summary.data?.stages ?? [];

  return (
    <Card
      title="Skipped Trades"
      subtitle="every setup the bot rejected — the failed gate, exact reason, and market snapshot"
      right={<Badge text={`${stages.reduce((s, x) => s + x.count, 0)} skipped`} tone="amber" />}
    >
      <div className="toolbar">
        <div className="search">
          <Icon name="info" size={15} className="search-icon" />
          <input placeholder="Search reason / symbol / gate…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="chips">
          <button className={`chip-btn ${stage === "all" ? "active" : ""}`} onClick={() => setStage("all")}>all</button>
          {stages.slice(0, 8).map((s) => (
            <button key={s.stage} className={`chip-btn ${stage === s.stage ? "active" : ""}`} onClick={() => setStage(s.stage)}>
              {s.stage} <span className="dim">{s.count}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="tablewrap">
        <table className="data-table">
          <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Category</th><th>Failed gate</th><th>Reason</th><th>Snapshot</th></tr></thead>
          <tbody>
            {trades.map((t) => {
              const isOpen = open === t.id;
              const hasSnap = t.snapshot && Object.keys(t.snapshot).length > 0;
              return (
                <Fragment key={t.id}>
                  <tr>
                    <td className="dim mono">{hhmmss(t.ts)}</td>
                    <td><b>{t.symbol}</b></td>
                    <td className="dim">{t.side}</td>
                    <td><Badge text={t.category} tone={catTone(t.category)} /></td>
                    <td><Badge text={t.stage} tone="amber" /></td>
                    <td>{t.reason}</td>
                    <td>
                      {hasSnap ? (
                        <button className="btn btn-ghost btn-sm" onClick={() => setOpen(isOpen ? null : t.id)}>
                          <Icon name="chevron" size={12} className={isOpen ? "rot-180" : undefined} /> {isOpen ? "Hide" : "View"}
                        </button>
                      ) : <span className="dim" style={{ fontSize: 11 }}>none captured</span>}
                    </td>
                  </tr>
                  {isOpen && hasSnap && (
                    <tr>
                      <td colSpan={7} style={{ background: "var(--surface-2, #121214)" }}>
                        <div className="form-grid-3" style={{ padding: "6px 4px" }}>
                          {Object.entries(t.snapshot).map(([k, v]) => v == null ? null : (
                            <div key={k} className="risk-item"><span className="dim">{k.replace(/_/g, " ")}</span><b style={{ fontSize: 12 }}>{String(v)}</b></div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {trades.length === 0 && (
              <tr><td colSpan={7} className="dim ta-center" style={{ padding: 20 }}>
                No skipped trades match — the bot has not rejected a setup{q || stage !== "all" ? " for this filter" : " yet"}.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function stTone(s: string) { return s === "healthy" || s === "up" ? "green" : s === "down" || s === "error" ? "red" : "amber"; }

function SystemHealth() {
  const rd = useLive<Readiness>("/production/readiness", 6000);
  const os = useLive<BotOsSnap>("/bot-os", 8000);
  const r = rd.data, o = os.data;
  return (
    <div className="grid-2-eq">
      <Card title="Production Readiness" subtitle={r?.summary ?? "operational health"}
        right={r && <Badge text={r.status} tone={stTone(r.status) as any} />}>
        {r && (
          <>
            <div className="risk-list">
              {r.checks.map((c) => (
                <div className="risk-item" key={c.name}>
                  <span className="dim">{c.name}</span>
                  <span className="row-actions" style={{ gap: 6 }}>
                    <span className="dim" style={{ fontSize: 11 }}>{c.detail}</span>
                    <Badge text={c.ok ? "ok" : c.level} tone={c.ok ? "green" : stTone(c.level) as any} />
                  </span>
                </div>
              ))}
            </div>
            <p className="dim" style={{ fontSize: 11, marginTop: 8 }}>
              Memory {r.memory_mb ?? "—"} MB · uptime {r.uptime_s ? `${Math.round(r.uptime_s / 60)}m` : "—"} ·
              data {r.data_freshness?.with_data ?? 0}/{r.data_freshness?.datasets ?? 0} cached
            </p>
          </>
        )}
      </Card>
      <Card title="Bot OS — engine map" subtitle={o?.architecture ?? "service / event layer"}
        right={o && <Badge text={`${o.up}/${o.engines} up`} tone={stTone(o.status) as any} />}>
        {o && (
          <div className="risk-list">
            {o.services.map((s) => (
              <div className="risk-item" key={s.name}>
                <span><b style={{ fontSize: 12 }}>{s.name}</b> <span className="dim" style={{ fontSize: 11 }}>· {s.desc}</span></span>
                <Badge text={s.state} tone={stTone(s.state) as any} />
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

const LEVELS = ["All", "info", "warning", "error"] as const;
const tone = (l: string) => ({ info: "blue", warning: "amber", error: "red" }[l] as any) ?? "default";

export default function LogsPage() {
  const { data, error, loading } = useLive<LogRow[]>("/ledger/logs?limit=300", 2500);
  const [level, setLevel] = usePref<(typeof LEVELS)[number]>("logs.level", "All");
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

      <SystemHealth />

      <SkippedTrades />

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
