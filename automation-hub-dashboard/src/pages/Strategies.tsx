import { useState } from "react";
import { Badge, PageHeader } from "../components/common/ui";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import CustomBuilder from "../components/strategy/CustomBuilder";
import { useApp } from "../app-context";
import { apiGet, apiPostJson, useLive, type StrategyList, type StrategyPerformance, type MarketCatalog } from "../lib/api";
import { signedMoney, signedNum } from "../lib/format";

function PreBuilt() {
  const app = useApp();
  const list = useLive<StrategyList>("/strategy/list", 5000);
  const perf = useLive<StrategyPerformance>("/strategy/performance", 4000);
  const active = list.data?.active;
  const [busy, setBusy] = useState<string | null>(null);

  const activate = async (key: string, label: string) => {
    setBusy(key);
    try {
      const r = await apiPostJson<any>("/strategy/select", { strategy: key });
      if (r?.error || r?.detail) app.toast(r.error || r.detail, "error");
      else { app.toast(`Activated ${label} — engine now trading it (paper)`, "success"); list.refetch(); }
    } catch { app.toast("Switching strategy needs the webhook secret", "error"); }
    finally { setBusy(null); }
  };

  return (
    <>
      {list.error && !list.data && (
        <div className="card" style={{ borderColor: "#ef4444" }}>
          <Icon name="warning" size={15} className="neg" /> Backend not reachable.
        </div>
      )}
      <div className="card">
        <div className="tablewrap">
          <table className="data-table">
            <thead><tr><th>Strategy</th><th>Description</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {(list.data?.strategies ?? []).map((s) => (
                <tr key={s.key}>
                  <td><b>{s.label}</b></td>
                  <td className="dim">{s.desc}</td>
                  <td>{s.key === active
                    ? <Badge text={`Active · ${list.data?.timeframe}`} tone="green" />
                    : <Badge text="Available" tone="default" />}</td>
                  <td style={{ textAlign: "right" }}>
                    {s.key === active
                      ? <span className="dim" style={{ fontSize: 12 }}><Icon name="check" size={13} /> in use</span>
                      : <button className="btn btn-soft sm" disabled={busy !== null} onClick={() => activate(s.key, s.label)}>
                          {busy === s.key ? "Activating…" : "Activate"}
                        </button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="dim" style={{ marginTop: 8 }}>
          Click <b>Activate</b> to switch the live engine to that strategy (paper mode) — the choice is
          saved and every symbol starts trading it. Validated reference (BTC/ETH 4h, walk-forward,
          fees+slippage): trend strategies profit factor ~1.2 out-of-sample.
        </p>
      </div>

      {perf.data && (
        <Card title={`Live Performance — ${perf.data.strategy}`} subtitle={`${perf.data.mode} · ${perf.data.trades} paper trades`}>
          <div className="tablewrap">
            <table className="data-table">
              <tbody>
                <tr><td className="dim">Win rate</td><td>{perf.data.win_rate.toFixed(1)}%</td>
                    <td className="dim">Profit factor</td><td className={perf.data.profit_factor >= 1 ? "pos" : "neg"}>{perf.data.profit_factor.toFixed(2)}</td></tr>
                <tr><td className="dim">Realized P&amp;L</td><td className={perf.data.realized_pnl >= 0 ? "pos" : "neg"}>{signedMoney(perf.data.realized_pnl)}</td>
                    <td className="dim">Max drawdown</td><td className="amber">{perf.data.max_drawdown_pct.toFixed(1)}%</td></tr>
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

export default function StrategiesPage() {
  const [tab, setTab] = useState<"Pre-built" | "Marketplace" | "Custom Builder">("Pre-built");

  return (
    <>
      <PageHeader title="Strategies" subtitle="choose a built-in strategy, browse the marketplace, or build your own · paper mode" />

      <StrategyLeague />
      <div className="tabs standalone">
        {(["Pre-built", "Marketplace", "Custom Builder"] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === "Pre-built" ? <PreBuilt /> : tab === "Marketplace" ? <Marketplace /> : <CustomBuilder />}
    </>
  );
}

function Marketplace() {
  const app = useApp();
  const cat = useLive<MarketCatalog>("/marketplace", 6000);
  const [rank, setRank] = useState<{ ranking: { strategy: string; net_r: number; win_rate: number; profit_factor: number }[]; best: any } | null>(null);
  const [busy, setBusy] = useState(false);
  const d = cat.data;

  const act = async (fn: () => Promise<any>, ok: string) => {
    try { const r = await fn(); if (r?.error || r?.detail) app.toast(r.error || r.detail, "error"); else { app.toast(ok, "success"); cat.refetch(); } }
    catch { app.toast("Action needs the webhook secret", "error"); }
  };
  const clone = (name: string) => act(() => apiPostJson("/marketplace/clone-template", { template: name }), `Cloned ${name} to your library`);
  const favorite = (id: string) => act(() => apiPostJson(`/marketplace/${id}/favorite`, {}), "Updated favorite");
  const tagIt = (id: string, current: string[]) => {
    const t = window.prompt("Tags (comma-separated)", current.join(", "));
    if (t === null) return;
    act(() => apiPostJson(`/marketplace/${id}/tags`, { tags: t.split(",").map((x) => x.trim()).filter(Boolean) }), "Tags updated");
  };
  const runRank = async () => {
    setBusy(true);
    try { setRank(await apiGet(`/marketplace/rank?symbol=BTCUSDT&timeframe=15m&strategies=Decision Brain,Trend Following,Supply/Demand,EMA 20/50&limit=600`)); }
    catch { /* ignore */ } finally { setBusy(false); }
  };

  return (
    <>
      <Card title="Performance Ranking" subtitle="which strategy makes money on BTC 15m (real replay)"
        right={<button className="btn btn-soft" disabled={busy} onClick={runRank}><Icon name="chart" size={13} /> {busy ? "Ranking…" : "Rank"}</button>}>
        {!rank ? <div className="dim ta-center" style={{ padding: 12 }}>Run a ranking to compare strategies by net R.</div> : (
          <table className="data-table" style={{ fontSize: 12 }}>
            <thead><tr><th>#</th><th>Strategy</th><th>Net R</th><th>PF</th><th>Win%</th></tr></thead>
            <tbody>{rank.ranking.map((r, i) => (
              <tr key={r.strategy}><td className="dim">{i + 1}</td><td><b>{r.strategy}</b></td>
                <td className={r.net_r >= 0 ? "pos" : "neg"}>{signedNum(r.net_r)}R</td><td>{r.profit_factor}</td><td className="dim">{r.win_rate}%</td></tr>
            ))}</tbody>
          </table>
        )}
      </Card>

      <Card title="My Library" subtitle={`${d?.counts?.library ?? 0} saved · ${d?.counts?.favorites ?? 0} favorite`}>
        {(d?.library?.length ?? 0) === 0 ? <div className="dim ta-center" style={{ padding: 14 }}>Clone a template below to start your library.</div> : (
          <div className="scan-grid">
            {d!.library.map((s) => (
              <div className="scan-card" key={s.id} style={{ ["--sc-accent" as any]: s.favorite ? "var(--gold)" : "var(--purple)" }}>
                <div className="row-actions" style={{ justifyContent: "space-between" }}>
                  <b>{s.name}</b>
                  <button className="icon-btn sm" title="Favorite" onClick={() => favorite(s.id)} style={{ color: s.favorite ? "var(--gold)" : "var(--dim)" }}><Icon name="target" size={13} /></button>
                </div>
                <span className="dim" style={{ fontSize: 11 }}>{s.description}</span>
                <div className="row-actions" style={{ gap: 4, flexWrap: "wrap" }}>
                  {s.tags.map((t) => <span key={t} className="ui-badge" style={{ background: "rgba(139,92,246,0.14)", color: "var(--purple-2)" }}>{t}</span>)}
                </div>
                <div className="row-actions" style={{ gap: 6 }}>
                  <button className="btn btn-soft sm" onClick={() => tagIt(s.id, s.tags)}>Tags</button>
                  <span className="dim" style={{ fontSize: 11 }}>v{s.version} · {s.timeframe ?? ""}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Templates" subtitle="clone a rule-based built-in into your editable library">
        <div className="scan-grid">
          {(d?.templates ?? []).map((t) => (
            <div className="scan-card" key={t.id}>
              <div className="row-actions" style={{ justifyContent: "space-between" }}>
                <b>{t.name}</b><span className="dim mono" style={{ fontSize: 10 }}>v{t.version}</span>
              </div>
              <span className="dim" style={{ fontSize: 11 }}>{t.description}</span>
              {t.clonable
                ? <button className="btn btn-soft sm" onClick={() => clone(t.name)}><Icon name="layers" size={12} /> Clone to library</button>
                : <span className="dim" style={{ fontSize: 11 }}>Built-in engine · activate on Pre-built</span>}
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}


type LeagueData = {
  available: boolean; detail?: string; data_source?: string; symbols?: string[];
  table?: { strategy: string; trades: number; win_rate: number | null; expectancy_r: number | null;
    net_r: number; profit_factor: number | null; max_drawdown_pct: number; verdict: string }[];
  correlations?: { a: string; b: string; correlation: number; relation: string }[];
  best_combo?: { a: string; b: string; correlation: number } | null;
  guidance?: string[];
};

const vTone = (v: string) => v === "earning" ? "green" : v === "losing" ? "red" : v === "breakeven" ? "amber" : "default";
const rTone = (r: string) => r === "diversifying" ? "green" : r === "redundant" ? "red" : "amber";

function StrategyLeague() {
  const lg = useLive<LeagueData>("/strategy/league?symbols=BTCUSDT,ETHUSDT&timeframe=1h&bars=2500", 120000);
  const d = lg.data;
  return (
    <Card title="Strategy League" subtitle="every strategy on the SAME real candles — ranked by what pays, with correlations"
      right={d?.available ? <Badge text={`real data · ${d.symbols?.join(" + ")}`} tone="green" /> : undefined}>
      {!d ? (
        <div className="dim" style={{ padding: 12 }}>Running the league on real candles…</div>
      ) : !d.available ? (
        <div className="dim" style={{ padding: 12 }}>{d.detail}</div>
      ) : (
        <>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
              <thead><tr className="dim" style={{ textAlign: "left" }}>
                <th style={{ padding: "4px 10px 4px 0" }}>#</th><th>Strategy</th><th>Verdict</th>
                <th>Expectancy</th><th>Win rate</th><th>Trades</th><th>Net R</th><th>PF</th><th>Max DD</th>
              </tr></thead>
              <tbody>
                {d.table?.map((r, i) => (
                  <tr key={r.strategy} style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
                    <td className="dim" style={{ padding: "5px 10px 5px 0" }}>{i + 1}</td>
                    <td><b>{r.strategy}</b></td>
                    <td><Badge text={r.verdict} tone={vTone(r.verdict) as any} /></td>
                    <td className={(r.expectancy_r ?? 0) >= 0 ? "green" : "red"}>
                      {r.expectancy_r != null ? `${r.expectancy_r >= 0 ? "+" : ""}${r.expectancy_r}R` : "—"}</td>
                    <td>{r.win_rate != null ? `${r.win_rate}%` : "—"}</td>
                    <td className="dim">{r.trades}</td>
                    <td className={r.net_r >= 0 ? "green" : "red"}>{r.net_r >= 0 ? "+" : ""}{r.net_r}</td>
                    <td>{r.profit_factor ?? "—"}</td>
                    <td className="dim">{r.max_drawdown_pct}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {(d.correlations?.length ?? 0) > 0 && (
            <>
              <div className="card-subtitle" style={{ marginTop: 12, marginBottom: 6 }}>
                How they move together <span className="dim">(daily return correlation)</span>
              </div>
              <div className="row-actions" style={{ justifyContent: "flex-start", gap: 6, flexWrap: "wrap" }}>
                {d.correlations!.map((c, i) => (
                  <span key={i} className="ui-badge" style={{ background: "var(--card-2)" }}>
                    {c.a} × {c.b}: <b style={{ margin: "0 4px" }}>{c.correlation}</b>
                    <Badge text={c.relation} tone={rTone(c.relation) as any} />
                  </span>
                ))}
              </div>
            </>
          )}

          {d.guidance?.map((g, i) => (
            <p key={i} className="dim" style={{ marginTop: i === 0 ? 10 : 4, fontSize: 12 }}>
              <Icon name="info" size={12} /> {g}
            </p>
          ))}
        </>
      )}
    </Card>
  );
}
