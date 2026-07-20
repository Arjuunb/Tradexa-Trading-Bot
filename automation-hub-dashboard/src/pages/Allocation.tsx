import { useEffect, useMemo, useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import Doughnut from "../components/chart/Doughnut";
import { PageHeader, StatCard } from "../components/common/ui";
import { useApp } from "../app-context";
import { apiGet, useLive, type ControlOptions, type PaperAccount } from "../lib/api";

/** Capital Allocation Planner — split capital across strategy "sleeves" and see
 *  the real risk budget each one gets, plus the portfolio's total capital-at-risk.
 *  Deterministic math on YOUR numbers (no fabricated returns). Note: the paper
 *  engine runs ONE strategy live at a time today — this is a planning tool for how
 *  you'd allocate across a multi-strategy book. */

interface Sleeve { id: number; strategy: string; alloc: number; risk: number; maxpos: number; }
const COLORS = ["#eab54f", "#22c55e", "#3b82f6", "#a78bfa", "#ef4444", "#06b6d4", "#ec4899", "#84cc16"];
const KEY = "nexus.allocation.sleeves.v1";
const money = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

const DEFAULT: Sleeve[] = [
  { id: 1, strategy: "Decision Brain", alloc: 50, risk: 1, maxpos: 3 },
  { id: 2, strategy: "Supply/Demand", alloc: 30, risk: 0.75, maxpos: 2 },
];

export default function AllocationPage() {
  const { go } = useApp();
  const acct = useLive<PaperAccount>("/paper/account", 8000);
  const [opts, setOpts] = useState<ControlOptions | null>(null);
  const [capital, setCapital] = useState(20000);
  const [sleeves, setSleeves] = useState<Sleeve[]>(() => {
    try { const s = localStorage.getItem(KEY); return s ? JSON.parse(s) : DEFAULT; } catch { return DEFAULT; }
  });

  useEffect(() => { apiGet<ControlOptions>("/control/options").then(setOpts).catch(() => {}); }, []);
  useEffect(() => { if (acct.data?.current_equity) setCapital(Math.round(acct.data.current_equity)); }, [acct.data?.current_equity]);
  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(sleeves)); } catch { /* noop */ } }, [sleeves]);

  const patch = (id: number, p: Partial<Sleeve>) => setSleeves((s) => s.map((x) => (x.id === id ? { ...x, ...p } : x)));
  const add = () => setSleeves((s) => [...s, { id: Math.max(0, ...s.map((x) => x.id)) + 1, strategy: opts?.strategies?.[0] ?? "Decision Brain", alloc: 10, risk: 1, maxpos: 2 }]);
  const remove = (id: number) => setSleeves((s) => s.filter((x) => x.id !== id));

  const rows = useMemo(() => sleeves.map((s, i) => {
    const capitalAlloc = capital * (s.alloc / 100);
    const riskPerTrade = capitalAlloc * (s.risk / 100);
    const maxAtRisk = riskPerTrade * s.maxpos;      // if every slot is filled and all hit stop
    return { ...s, color: COLORS[i % COLORS.length], capitalAlloc, riskPerTrade, maxAtRisk };
  }), [sleeves, capital]);

  const totalAlloc = rows.reduce((a, r) => a + r.alloc, 0);
  const allocatedCash = rows.reduce((a, r) => a + r.capitalAlloc, 0);
  const totalAtRisk = rows.reduce((a, r) => a + r.maxAtRisk, 0);
  const blendedRisk = capital > 0 ? rows.reduce((a, r) => a + r.riskPerTrade, 0) / capital * 100 : 0;
  const over = totalAlloc > 100.0001;
  const slices = rows.filter((r) => r.alloc > 0).map((r) => ({ name: r.strategy, value: r.capitalAlloc, color: r.color }));
  if (totalAlloc < 100) slices.push({ name: "Unallocated", value: capital * (100 - totalAlloc) / 100, color: "#2a2a30" });

  return (
    <>
      <PageHeader title="Capital Allocation Planner"
        subtitle="Split capital across strategy sleeves and size each one's real risk budget — a plan for a multi-strategy book."
        actions={<button className="btn btn-soft btn-sm" onClick={() => go("Fleet Manager")}><Icon name="bot" size={13} /> Fleet Manager</button>}
      />

      <div className="stat-row">
        <StatCard label="Total capital" value={money(capital)} sub={acct.data ? "from paper account" : "editable"} />
        <StatCard label="Allocated" value={`${totalAlloc.toFixed(0)}%`} tone={over ? "red" : totalAlloc === 100 ? "green" : "amber"} sub={money(allocatedCash)} />
        <StatCard label="Blended risk / trade" value={`${blendedRisk.toFixed(2)}%`} sub="capital-weighted" />
        <StatCard label="Max capital at risk" value={money(totalAtRisk)} tone={totalAtRisk > capital * 0.1 ? "red" : "green"} sub={`${(capital ? totalAtRisk / capital * 100 : 0).toFixed(1)}% if all stops hit`} />
      </div>

      {over && <div className="banner" style={{ marginBottom: 12 }}><Icon name="warning" size={13} className="neg" /> Sleeves total {totalAlloc.toFixed(0)}% — over-allocated. Trim to 100% or you'd be leveraged beyond your capital.</div>}

      <div className="grid-2-1">
        <Card title="Strategy sleeves" subtitle="allocation % · risk per trade · max concurrent positions"
          right={<div className="row-actions" style={{ gap: 6 }}>
            <label className="dim" style={{ fontSize: 12 }}>Capital $
              <input className="rule-num" style={{ width: 100, marginLeft: 6 }} type="number" value={capital} onChange={(e) => setCapital(Math.max(0, Number(e.target.value)))} /></label>
            <button className="btn btn-soft btn-sm" onClick={add}><Icon name="plus" size={12} /> Sleeve</button>
          </div>}>
          <div className="tablewrap">
            <table className="data-table" style={{ fontSize: 12.5 }}>
              <thead><tr><th>Strategy</th><th>Alloc %</th><th>Risk %</th><th>Max pos</th><th style={{ textAlign: "right" }}>Capital</th><th style={{ textAlign: "right" }}>Risk/trade</th><th style={{ textAlign: "right" }}>Max at risk</th><th></th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: r.color, marginRight: 6 }} />
                      <select value={r.strategy} onChange={(e) => patch(r.id, { strategy: e.target.value })}>
                        {(opts?.strategies ?? [r.strategy]).filter((s) => s !== "Custom Strategy").map((s) => <option key={s}>{s}</option>)}
                      </select>
                    </td>
                    <td><input className="rule-num" style={{ width: 60 }} type="number" value={r.alloc} onChange={(e) => patch(r.id, { alloc: Number(e.target.value) })} /></td>
                    <td><input className="rule-num" style={{ width: 60 }} type="number" step="0.25" value={r.risk} onChange={(e) => patch(r.id, { risk: Number(e.target.value) })} /></td>
                    <td><input className="rule-num" style={{ width: 50 }} type="number" value={r.maxpos} onChange={(e) => patch(r.id, { maxpos: Math.max(1, Math.round(Number(e.target.value))) })} /></td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{money(r.capitalAlloc)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{money(r.riskPerTrade)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }} className={r.maxAtRisk > r.capitalAlloc * 0.2 ? "neg" : ""}>{money(r.maxAtRisk)}</td>
                    <td><button className="chip-btn" onClick={() => remove(r.id)} title="Remove"><Icon name="close" size={11} /></button></td>
                  </tr>
                ))}
                {rows.length === 0 && <tr><td colSpan={8} className="dim ta-center" style={{ padding: 16 }}>Add a sleeve to start planning.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Allocation" subtitle={`${money(allocatedCash)} of ${money(capital)}`}>
          <Doughnut data={slices} height={220} centerLabel="allocated" centerValue={`${totalAlloc.toFixed(0)}%`} centerTone={over ? "neg" : "default"} />
        </Card>
      </div>

      <div className="banner" style={{ marginTop: 12, fontSize: 11.5 }}><Icon name="info" size={12} />
        Deterministic capital &amp; risk math on your own numbers — no projected returns. The paper engine runs one strategy live at a time today;
        this plans how you'd split a book across strategies. "Max at risk" assumes every position in every sleeve hits its stop at once (worst case).</div>
    </>
  );
}
