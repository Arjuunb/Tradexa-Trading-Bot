import { lazy, Suspense, useMemo, useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import Modal from "../components/common/Modal";
import { PageHeader, StatCard } from "../components/common/ui";
import { useApp } from "../app-context";
import {
  apiPostJson, apiGet, apiDelete, useLive,
  type BlockCatalog, type BlockDef, type CustomRule, type CustomSpec,
  type SimResult, type AIStrategyReview, type StrategyVersion,
} from "../lib/api";

// Compact field-level diff between two strategy definitions (version vs current).
const DEF_KEYS = ["name", "symbol", "timeframe", "side", "entry", "exit", "stop", "target",
  "risk_per_trade_pct", "max_trades_per_day", "session", "market"];
const short = (v: unknown): string => {
  if (v == null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
};
function diffDefs(from: Record<string, unknown>, to: Record<string, unknown>) {
  const out: { key: string; from: string; to: string }[] = [];
  for (const k of DEF_KEYS) {
    const a = JSON.stringify(from?.[k] ?? null), b = JSON.stringify(to?.[k] ?? null);
    if (a !== b) out.push({ key: k, from: short(from?.[k]), to: short(to?.[k]) });
  }
  return out;
}

const StrategyCanvas = lazy(() => import("../components/strategy/StrategyCanvas"));
const TFS = ["15m", "1h", "4h", "1d"];
const CONF_TONE: Record<string, string> = { "Very High": "green", High: "green", Medium: "amber", Low: "red", "Very Low": "red" };
const WARN_TONE: Record<string, string> = { danger: "red", warning: "amber", ok: "green" };

const EMPTY: CustomSpec = {
  name: "My Strategy", market: "crypto", symbol: "BTCUSDT", timeframe: "4h", side: "long",
  entry: { op: "AND", rules: [] }, stop: { type: "atr", mult: 1.5, period: 14 },
  target: { type: "rr", rr: 2 }, risk_per_trade_pct: 0.01, max_trades_per_day: 0,
};

export default function StrategyStudioPage() {
  const { toast, go } = useApp();
  const { data: catalog } = useLive<BlockCatalog>("/strategy/blocks", 300000);
  const templates = useLive<{ templates: (CustomSpec & { id: string; description: string })[] }>("/strategy/templates", 300000);
  const saved = useLive<CustomSpec[]>("/strategy/custom", 6000);

  const [spec, setSpec] = useState<CustomSpec>(EMPTY);
  const [sim, setSim] = useState<SimResult | null>(null);
  const [review, setReview] = useState<AIStrategyReview | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [mode, setMode] = useState<"form" | "canvas">("form");
  // version history / compare
  const [histFor, setHistFor] = useState<CustomSpec | null>(null);
  const [versions, setVersions] = useState<StrategyVersion[] | null>(null);
  const [compareV, setCompareV] = useState<number | null>(null);

  const patch = (p: Partial<CustomSpec>) => setSpec((s) => ({ ...s, ...p }));
  const blockDefs = useMemo(() => {
    const m = new Map<string, BlockDef>();
    catalog?.categories.forEach((c) => c.blocks.forEach((b) => m.set(b.type, b)));
    return m;
  }, [catalog]);

  const addBlock = (b: BlockDef) => {
    const rule: CustomRule = { type: b.type };
    b.params.forEach((p) => { rule[p.name] = p.default; });
    setSpec((s) => ({ ...s, entry: { ...s.entry, rules: [...s.entry.rules, rule] } }));
    setReview(null); setSim(null);
  };
  const setRule = (i: number, r: CustomRule) =>
    setSpec((s) => ({ ...s, entry: { ...s.entry, rules: s.entry.rules.map((x, j) => (j === i ? r : x)) } }));
  const delRule = (i: number) =>
    setSpec((s) => ({ ...s, entry: { ...s.entry, rules: s.entry.rules.filter((_, j) => j !== i) } }));

  // exit conditions (same blocks/engine as entry — a separate condition tree)
  const exitRules = spec.exit?.rules ?? [];
  const patchExit = (p: Partial<NonNullable<CustomSpec["exit"]>>) => { patch({ exit: { ...(spec.exit ?? {}), ...p } }); setReview(null); setSim(null); };
  const addExitBlock = (b: BlockDef) => { const rule: CustomRule = { type: b.type }; b.params.forEach((p) => { rule[p.name] = p.default; }); patchExit({ op: spec.exit?.op ?? "OR", rules: [...exitRules, rule] }); };
  const setExitRule = (i: number, r: CustomRule) => patchExit({ rules: exitRules.map((x, j) => (j === i ? r : x)) });
  const delExitRule = (i: number) => patchExit({ rules: exitRules.filter((_, j) => j !== i) });

  const backtest = async () => {
    setBusy("sim");
    try { setSim(await apiPostJson<SimResult>("/strategy/custom/simulate", { spec, bars: 3000 })); }
    catch { toast("Backtest failed", "error"); } finally { setBusy(""); }
  };
  const aiReview = async () => {
    setBusy("review");
    try { setReview(await apiPostJson<AIStrategyReview>("/strategy/ai-review", { spec, bars: 2000 })); }
    catch { toast("AI review failed", "error"); } finally { setBusy(""); }
  };
  const save = async () => {
    if (!spec.entry.rules.length) { toast("Add at least one condition first", "error"); return; }
    try { const r = await apiPostJson<CustomSpec>("/strategy/custom", spec); setSpec(r); saved.refetch(); toast("Strategy saved", "success"); }
    catch { toast("Save failed", "error"); }
  };
  const loadTemplate = (t: CustomSpec & { id: string }) => {
    const { id, ...rest } = t as any;   // drop the template id so it saves as a new strategy
    setSpec({ ...EMPTY, ...rest, name: `${t.name} (my copy)` }); setReview(null); setSim(null);
    toast(`Loaded template: ${t.name}`, "info");
  };
  const load = (s: CustomSpec) => { setSpec(s); setReview(null); setSim(null); };
  const deploy = async (s: CustomSpec) => {
    try { await apiPostJson(`/strategy/custom/${s.id}/deploy`, {}); toast(`"${s.name}" deployed to paper trading`, "success"); }
    catch { toast("Deploy failed", "error"); }
  };
  const favorite = async (s: CustomSpec) => {
    try { await apiPostJson(`/strategy/custom/${s.id}/favorite`, { on: !(s as any).favorite }); saved.refetch(); }
    catch { toast("Failed", "error"); }
  };
  const rename = async (s: CustomSpec) => {
    const name = window.prompt("Rename strategy:", s.name); if (!name?.trim()) return;
    try { await apiPostJson(`/strategy/custom/${s.id}/meta`, { name }); saved.refetch(); toast("Renamed", "success"); }
    catch { toast("Failed", "error"); }
  };
  const duplicate = async (s: CustomSpec) => {
    try { await apiPostJson(`/strategy/custom/${s.id}/duplicate`, {}); saved.refetch(); toast("Cloned", "success"); }
    catch { toast("Failed", "error"); }
  };
  const openHistory = async (s: CustomSpec) => {
    setHistFor(s); setVersions(null); setCompareV(null);
    try { const r = await apiGet<{ versions: StrategyVersion[] }>(`/strategy/custom/${s.id}/history`); setVersions(r.versions ?? []); }
    catch { toast("Could not load history", "error"); setVersions([]); }
  };
  const restoreVersion = async (v: number) => {
    if (!histFor?.id) return;
    if (!window.confirm(`Restore version ${v}? Your current version is saved to history first, so this is undoable.`)) return;
    try {
      const r = await apiPostJson<CustomSpec>(`/strategy/custom/${histFor.id}/restore`, { v });
      saved.refetch(); setSpec(r); setHistFor(null); toast(`Restored to v${v} — now editing`, "success");
    } catch { toast("Restore failed", "error"); }
  };
  const del = async (s: CustomSpec) => {
    if (!window.confirm(`Delete "${s.name}"?`)) return;
    try { await apiDelete(`/strategy/custom/${s.id}`); saved.refetch(); toast("Deleted", "info"); }
    catch { toast("Failed", "error"); }
  };
  const exportSpec = () => {
    const blob = new Blob([JSON.stringify(spec, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `${spec.name.replace(/\s+/g, "-").toLowerCase()}.json`; a.click();
  };

  const r = sim?.results;
  const configFields = (
    <div className="form-grid-3" style={{ marginTop: 14 }}>
      <label className="dim">Stop
        <div className="chips" style={{ marginTop: 4 }}>
          {(["atr", "pct"] as const).map((tp) => <button key={tp} className={`chip-btn ${spec.stop.type === tp ? "active" : ""}`} onClick={() => patch({ stop: { ...spec.stop, type: tp } })}>{tp}</button>)}
          <input className="rule-num" type="number" step="0.1" value={spec.stop.type === "atr" ? (spec.stop.mult ?? 1.5) : (spec.stop.pct ?? 2)}
            onChange={(e) => patch({ stop: { ...spec.stop, [spec.stop.type === "atr" ? "mult" : "pct"]: Number(e.target.value) } })} />
        </div>
      </label>
      <label className="dim">Target
        <div className="chips" style={{ marginTop: 4 }}>
          {(["rr", "pct"] as const).map((tp) => <button key={tp} className={`chip-btn ${spec.target.type === tp ? "active" : ""}`} onClick={() => patch({ target: { ...spec.target, type: tp } })}>{tp}</button>)}
          <input className="rule-num" type="number" step="0.1" value={spec.target.type === "rr" ? (spec.target.rr ?? 2) : (spec.target.pct ?? 3)}
            onChange={(e) => patch({ target: { ...spec.target, [spec.target.type === "rr" ? "rr" : "pct"]: Number(e.target.value) } })} />
        </div>
      </label>
      <label className="dim">Risk / trade (%)
        <input className="rule-num" type="number" step="0.1" value={spec.risk_per_trade_pct * 100}
          onChange={(e) => patch({ risk_per_trade_pct: Number(e.target.value) / 100 })} />
      </label>
      <label className="dim">Session (UTC)
        <select className="rule-num" style={{ marginTop: 4 }}
          value={spec.session ? "custom" : "any"}
          onChange={(e) => {
            const s = catalog?.config.sessions.find((x) => x.key === e.target.value);
            patch({ session: !s || s.key === "any" ? null : { start: s.start, end: s.end } });
          }}>
          {(catalog?.config.sessions ?? [{ key: "any", label: "Any" } as any]).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
      </label>
    </div>
  );
  return (
    <>
      <PageHeader title="Strategy Studio"
        subtitle="Build strategies visually with condition blocks — no code. Compiles to the same engine that backtests, paper-trades, and (later) goes live."
        actions={<>
          <button className="btn btn-soft btn-sm" onClick={() => go("Strategies")}>Strategy Catalog</button>
          <button className="btn btn-soft btn-sm" onClick={() => go("Strategy Proof")}>Strategy Proof</button>
        </>} />

      {/* toolbar */}
      <div className="toolbar" style={{ gap: 8, flexWrap: "wrap" }}>
        <input className="rule-num" style={{ width: 180 }} value={spec.name}
          onChange={(e) => patch({ name: e.target.value })} title="Strategy name" />
        <input className="rule-num" style={{ width: 110 }} value={spec.symbol}
          onChange={(e) => patch({ symbol: e.target.value.toUpperCase() })} title="Symbol" />
        <div className="chips">{TFS.map((t) => <button key={t} className={`chip-btn ${spec.timeframe === t ? "active" : ""}`} onClick={() => patch({ timeframe: t })}>{t}</button>)}</div>
        <div className="chips">{(["long", "short"] as const).map((s) => <button key={s} className={`chip-btn ${spec.side === s ? "active" : ""}`} onClick={() => patch({ side: s })}>{s}</button>)}</div>
        <div className="chips">{(["form", "canvas"] as const).map((m) => <button key={m} className={`chip-btn ${mode === m ? "active" : ""}`} onClick={() => setMode(m)}>{m === "form" ? "Form" : "Canvas"}</button>)}</div>
        <button className="btn btn-soft" onClick={backtest} disabled={busy === "sim"}><Icon name="history" size={13} /> {busy === "sim" ? "Testing…" : "Backtest"}</button>
        <button className="btn btn-soft" onClick={aiReview} disabled={busy === "review"}><Icon name="bot" size={13} /> {busy === "review" ? "Reviewing…" : "AI Review"}</button>
        <button className="btn btn-primary" onClick={save}><Icon name="check" size={13} /> Save</button>
        <button className="btn btn-soft" onClick={exportSpec} title="Export JSON"><Icon name="external" size={13} /></button>
      </div>

      {/* templates */}
      <Card title="Templates" subtitle="Start from a proven pattern, then tweak">
        <div className="chips" style={{ gap: 8 }}>
          {(templates.data?.templates ?? []).map((t) => (
            <button key={t.id} className="chip-btn" onClick={() => loadTemplate(t)} title={t.description}>{t.name}</button>
          ))}
          <button className="chip-btn" onClick={() => { setSpec(EMPTY); setReview(null); setSim(null); }}><Icon name="plus" size={12} /> Blank</button>
        </div>
      </Card>

      {mode === "canvas" ? (
        <>
          <Card title="Strategy Canvas" subtitle={`${spec.side.toUpperCase()} — drag a block's right dot to an AND/OR group, then the group to Entry. Zoom, mini-map, undo included.`}>
            <Suspense fallback={<div className="dim" style={{ padding: 20 }}>Loading canvas…</div>}>
              <StrategyCanvas spec={spec} catalog={catalog ?? undefined}
                onChange={(s) => { setSpec(s); setReview(null); setSim(null); }} />
            </Suspense>
          </Card>
          <Card title="Exit &amp; Risk" subtitle="Applies to the whole strategy">{configFields}</Card>
        </>
      ) : (
      <div className="grid-2-1">
        {/* builder */}
        <Card title="Entry Conditions" subtitle={`${spec.side.toUpperCase()} when ${spec.entry.op} of these are true`}>
          <div className="chips" style={{ marginBottom: 10 }}>
            {(["AND", "OR"] as const).map((op) => (
              <button key={op} className={`chip-btn ${spec.entry.op === op ? "active" : ""}`}
                onClick={() => patch({ entry: { ...spec.entry, op } })}>{op}</button>
            ))}
          </div>

          {spec.entry.rules.length === 0 && <div className="dim" style={{ padding: "6px 2px 12px" }}>Add condition blocks from the palette →</div>}
          {spec.entry.rules.map((rule, i) => {
            const def = blockDefs.get(rule.type);
            return (
              <div key={i} className="builder-rule">
                <span className={`rule-tag ${rule.negate ? "neg" : ""}`}>{rule.negate ? "NOT " : ""}{def?.label ?? rule.type}</span>
                {(def?.params ?? []).map((p) => (
                  p.type === "select" ? (
                    <select key={p.name} className="rule-num" value={String(rule[p.name] ?? p.default)}
                      onChange={(e) => setRule(i, { ...rule, [p.name]: e.target.value })} title={p.label}>
                      {(p.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input key={p.name} className="rule-num" type="number" value={Number(rule[p.name] ?? p.default)}
                      onChange={(e) => setRule(i, { ...rule, [p.name]: Number(e.target.value) })} title={p.label} />
                  )
                ))}
                <button className="chip-btn" title="Negate (NOT)" onClick={() => setRule(i, { ...rule, negate: !rule.negate })}>¬</button>
                <button className="chip-btn" title="Remove" onClick={() => delRule(i)}><Icon name="close" size={12} /></button>
              </div>
            );
          })}

          {configFields}
        </Card>

        {/* block palette */}
        <Card title="Blocks" subtitle="Click to add a condition">
          <div style={{ maxHeight: 520, overflowY: "auto" }}>
            {(catalog?.categories ?? []).map((cat) => (
              <div key={cat.key} style={{ marginBottom: 10 }}>
                <div className="dim" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, margin: "4px 0" }}>{cat.label}</div>
                <div className="chips">
                  {cat.blocks.map((b) => (
                    <button key={b.type} className="chip-btn" title={b.desc} onClick={() => addBlock(b)}>+ {b.label}</button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
      )}

      {/* exit conditions */}
      <Card title="Exit Conditions" subtitle="Close early when these fire — stop, target & the options below always apply">
        <div className="chips" style={{ marginBottom: 10, gap: 12, alignItems: "center" }}>
          <label className="dim" style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
            <input type="checkbox" checked={!!spec.exit?.ai_exit} onChange={(e) => patchExit({ ai_exit: e.target.checked })} /> AI exit on reversal
          </label>
          <span className="dim" style={{ fontSize: 12.5 }}>Break-even @R <input className="rule-num" style={{ width: 56 }} type="number" step="0.5" value={spec.exit?.breakeven_at_r ?? 0} onChange={(e) => patchExit({ breakeven_at_r: Number(e.target.value) })} /></span>
          <span className="dim" style={{ fontSize: 12.5 }}>Trail ATR <input className="rule-num" style={{ width: 56 }} type="number" step="0.5" value={spec.exit?.trail_atr ?? 0} onChange={(e) => patchExit({ trail_atr: Number(e.target.value) })} /></span>
          <span className="dim" style={{ fontSize: 12.5 }}>Time stop (bars) <input className="rule-num" style={{ width: 56 }} type="number" value={spec.exit?.time_stop_bars ?? 0} onChange={(e) => patchExit({ time_stop_bars: Number(e.target.value) })} /></span>
          {exitRules.length > 1 && (
            <span className="chips">{(["OR", "AND"] as const).map((op) => <button key={op} className={`chip-btn ${(spec.exit?.op ?? "OR") === op ? "active" : ""}`} onClick={() => patchExit({ op })}>{op}</button>)}</span>
          )}
        </div>
        {exitRules.map((rule, i) => {
          const def = blockDefs.get(rule.type);
          return (
            <div key={i} className="builder-rule">
              <span className={`rule-tag ${rule.negate ? "neg" : ""}`}>{rule.negate ? "NOT " : ""}{def?.label ?? rule.type}</span>
              {(def?.params ?? []).map((p) => (
                p.type === "select" ? (
                  <select key={p.name} className="rule-num" value={String(rule[p.name] ?? p.default)} onChange={(e) => setExitRule(i, { ...rule, [p.name]: e.target.value })} title={p.label}>
                    {(p.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <input key={p.name} className="rule-num" type="number" value={Number(rule[p.name] ?? p.default)} onChange={(e) => setExitRule(i, { ...rule, [p.name]: Number(e.target.value) })} title={p.label} />
                )
              ))}
              <button className="chip-btn" title="Negate" onClick={() => setExitRule(i, { ...rule, negate: !rule.negate })}>¬</button>
              <button className="chip-btn" title="Remove" onClick={() => delExitRule(i)}><Icon name="close" size={12} /></button>
            </div>
          );
        })}
        <select className="rule-num" style={{ marginTop: 6 }} value="" onChange={(e) => { const b = blockDefs.get(e.target.value); if (b) addExitBlock(b); e.target.value = ""; }}>
          <option value="">+ add exit condition…</option>
          {(catalog?.categories ?? []).map((c) => <optgroup key={c.key} label={c.label}>{c.blocks.map((b) => <option key={b.type} value={b.type}>{b.label}</option>)}</optgroup>)}
        </select>
      </Card>

      {/* AI review + backtest */}
      <div className="grid-2-eq">
        <Card title="AI Strategy Review" subtitle={review?.summary ?? "Analyse complexity, risk, strengths and confidence"}>
          {!review ? <div className="dim" style={{ padding: 10 }}>Click “AI Review” to analyse this strategy.</div> : (
            <>
              <div className="stat-row">
                <StatCard label="Confidence" value={review.confidence_level} tone={(CONF_TONE[review.confidence_level] ?? "default") as never} sub={`${review.estimated_confidence}%`} />
                <StatCard label="Complexity" value={review.complexity} sub={`${review.rule_count} rules`} />
                <StatCard label="Risk" value={review.risk_level} tone={review.risk_level === "high" ? "red" : review.risk_level === "elevated" ? "amber" : "green"} />
              </div>
              <div className="dim" style={{ margin: "10px 0 6px", fontSize: 13 }}>{review.expected_behaviour}</div>
              <ReviewList label="Strengths" items={review.strengths} cls="pos" />
              <ReviewList label="Weaknesses" items={review.weaknesses} cls="neg" />
              <ReviewList label="Improvements" items={review.improvements} cls="dim" />
              {review.warnings?.map((w, i) => <div key={i} className={WARN_TONE[w.level] === "red" ? "neg" : WARN_TONE[w.level] === "amber" ? "amber" : "pos"} style={{ fontSize: 12.5, marginTop: 4 }}>• {w.message}</div>)}
            </>
          )}
        </Card>

        <Card title="Backtest" subtitle={r ? `${r.total_trades} trades on real ${spec.symbol} ${spec.timeframe} candles` : "Run a backtest on real data"}>
          {!r ? <div className="dim" style={{ padding: 10 }}>Click “Backtest” to test on historical candles.</div> : (
            <div className="stat-row">
              <StatCard label="Net R" value={`${r.net_r >= 0 ? "+" : ""}${r.net_r}`} tone={r.net_r >= 0 ? "green" : "red"} />
              <StatCard label="Win Rate" value={`${r.win_rate}%`} tone={r.win_rate >= 50 ? "green" : "amber"} />
              <StatCard label="Profit Factor" value={String(r.profit_factor)} tone={r.profit_factor >= 1 ? "green" : "red"} />
              <StatCard label="Trades" value={String(r.total_trades)} sub={`${r.max_drawdown_pct}% max DD`} />
            </div>
          )}
        </Card>
      </div>

      {/* library */}
      <Card title="Strategy Library" subtitle={`${saved.data?.length ?? 0} saved`}>
        {!(saved.data ?? []).length ? <div className="dim" style={{ padding: 10 }}>No saved strategies yet — build one and hit Save.</div> : (
          <table className="data-table" style={{ fontSize: 12.5 }}>
            <thead><tr><th></th><th>Name</th><th>Symbol</th><th>Rules</th><th>Folder</th><th></th></tr></thead>
            <tbody>
              {(saved.data ?? []).map((s) => (
                <tr key={s.id}>
                  <td style={{ width: 24, cursor: "pointer", color: (s as any).favorite ? "var(--gold)" : "var(--dim)" }} onClick={() => favorite(s)} title="Favorite"><Icon name="check" size={13} /></td>
                  <td><b style={{ cursor: "pointer" }} onClick={() => load(s)}>{s.name}</b></td>
                  <td className="dim">{s.symbol} · {s.timeframe}</td>
                  <td className="dim">{s.entry?.rules?.length ?? 0}</td>
                  <td className="dim">{(s as any).folder ?? "—"}</td>
                  <td>
                    <div className="row-actions" style={{ gap: 4, justifyContent: "flex-end" }}>
                      <button className="chip-btn" onClick={() => load(s)} title="Edit">Edit</button>
                      <button className="chip-btn" onClick={() => openHistory(s)} title="Version history"><Icon name="history" size={12} />{(s.versions?.length ?? 0) > 0 ? ` ${s.versions!.length}` : ""}</button>
                      <button className="chip-btn" onClick={() => rename(s)} title="Rename"><Icon name="settings" size={12} /></button>
                      <button className="chip-btn" onClick={() => duplicate(s)} title="Clone"><Icon name="layers" size={12} /></button>
                      <button className="chip-btn" onClick={() => deploy(s)} title="Deploy to paper"><Icon name="rocket" size={12} /></button>
                      <button className="chip-btn" onClick={() => del(s)} title="Delete"><Icon name="close" size={12} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Modal open={!!histFor} title={`Version history — ${histFor?.name ?? ""}`} onClose={() => setHistFor(null)}>
        {versions == null ? <div className="dim">Loading…</div>
          : versions.length === 0 ? <div className="dim">No prior versions yet. Each edit you save creates a restore point here.</div>
          : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: "60vh", overflowY: "auto" }}>
            <div className="dim" style={{ fontSize: 11.5 }}>
              {versions.length} restore point{versions.length === 1 ? "" : "s"} · newest first. “Compare” diffs a version against the current saved strategy.
            </div>
            {[...versions].reverse().map((ver) => {
              const changes = histFor ? diffDefs(ver.spec, histFor as unknown as Record<string, unknown>) : [];
              const openCmp = compareV === ver.v;
              return (
                <div key={ver.v} style={{ border: "1px solid var(--card-border)", borderRadius: 8, padding: "9px 11px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <b style={{ fontSize: 12.5 }}>v{ver.v}</b>
                    <span className="dim" style={{ fontSize: 11.5 }}>{ver.name ?? histFor?.name} · {new Date(ver.at).toLocaleString()}</span>
                    <div className="row-actions" style={{ marginLeft: "auto", gap: 4 }}>
                      <button className="chip-btn" onClick={() => setCompareV(openCmp ? null : ver.v)}>{openCmp ? "Hide" : "Compare"}</button>
                      <button className="chip-btn" onClick={() => restoreVersion(ver.v)} title="Roll back to this version"><Icon name="history" size={11} /> Restore</button>
                    </div>
                  </div>
                  {openCmp && (
                    <div style={{ marginTop: 8, fontSize: 11.5 }}>
                      {changes.length === 0 ? <span className="dim">Identical to the current saved version.</span> : (
                        <table className="data-table" style={{ fontSize: 11.5 }}>
                          <thead><tr><th>Field</th><th>v{ver.v}</th><th>Current</th></tr></thead>
                          <tbody>
                            {changes.map((c) => (
                              <tr key={c.key}>
                                <td><b>{c.key}</b></td>
                                <td className="neg" style={{ maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis" }} title={c.from}>{c.from}</td>
                                <td className="pos" style={{ maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis" }} title={c.to}>{c.to}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Modal>
    </>
  );
}

function ReviewList({ label, items, cls }: { label: string; items: string[]; cls: string }) {
  if (!items?.length) return null;
  return (
    <div style={{ marginTop: 8 }}>
      <div className="dim" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <ul style={{ margin: "2px 0 0", paddingLeft: 18, fontSize: 12.5, lineHeight: 1.55 }}>
        {items.map((x, i) => <li key={i} className={cls}>{x}</li>)}
      </ul>
    </div>
  );
}
