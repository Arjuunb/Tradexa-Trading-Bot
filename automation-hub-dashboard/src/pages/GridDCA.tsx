import { useMemo, useState } from "react";
import Card from "../components/common/Card";
import Icon from "../components/common/Icon";
import { PageHeader, StatCard, Badge, Toggle, Field } from "../components/common/ui";
import { useApp } from "../app-context";

/** Grid & DCA strategy configuration + live preview.
 *  Everything on the right is DETERMINISTIC math derived from your inputs — grid
 *  lines, zones and per-grid profit are exact; annual performance and drawdown
 *  are clearly-labelled PROJECTIONS (assumptions, not guarantees). No fabricated
 *  market results. Execution is paper-only and gated by the safety flow. */

const EXCHANGES = ["Binance", "Bybit", "OKX"];
const PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT"];
const money = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const pct = (n: number) => `${n >= 0 ? "" : ""}${n.toFixed(2)}%`;
const num = (v: string, d = 0) => (v === "" || isNaN(Number(v)) ? d : Number(v));

// ─────────────────────────────── Grid ───────────────────────────────
interface GridCfg {
  exchange: string; pair: string; market: "spot" | "futures"; side: "long" | "short";
  investment: number; upper: number; lower: number; current: number; levels: number;
  geometric: boolean; tp: number; sl: number; trailing: boolean; maxPos: number; fee: number;
  roundtripsPerDay: number;
}
const GRID_DEFAULT: GridCfg = {
  exchange: "Binance", pair: "BTCUSDT", market: "futures", side: "long",
  investment: 1000, upper: 70000, lower: 60000, current: 64000, levels: 20,
  geometric: false, tp: 0, sl: 0, trailing: false, maxPos: 20, fee: 0.04, roundtripsPerDay: 3,
};

function gridPrices(c: GridCfg): number[] {
  const { lower, upper, levels, geometric } = c;
  const out: number[] = [];
  if (levels < 2 || lower <= 0 || upper <= lower) return out;
  if (geometric) {
    const r = Math.pow(upper / lower, 1 / (levels - 1));
    for (let i = 0; i < levels; i++) out.push(lower * Math.pow(r, i));
  } else {
    const step = (upper - lower) / (levels - 1);
    for (let i = 0; i < levels; i++) out.push(lower + i * step);
  }
  return out;
}

function gridMetrics(c: GridCfg) {
  const prices = gridPrices(c);
  const n = prices.length;
  const orderValue = n > 0 ? c.investment / n : 0;
  // per-gap % (geometric constant; arithmetic averaged)
  let gapPct = 0;
  if (n >= 2) {
    if (c.geometric) gapPct = (Math.pow(c.upper / c.lower, 1 / (n - 1)) - 1) * 100;
    else {
      let s = 0;
      for (let i = 1; i < n; i++) s += ((prices[i] - prices[i - 1]) / prices[i - 1]) * 100;
      gapPct = s / (n - 1);
    }
  }
  const netPerGridPct = gapPct - 2 * c.fee;              // one round-trip, net of fees
  const profitPerGrid = (orderValue * netPerGridPct) / 100;
  const cycleProfit = profitPerGrid * Math.max(0, n - 1); // every grid round-trips once
  const cycleYieldPct = c.investment > 0 ? (cycleProfit / c.investment) * 100 : 0;
  const dailyProfit = profitPerGrid * c.roundtripsPerDay;
  const annualPct = c.investment > 0 ? (dailyProfit * 365 / c.investment) * 100 : 0;
  // max unrealized drawdown if price falls to the lower bound (all buys below current filled)
  let ddAbs = 0;
  for (const p of prices) if (p < c.current) ddAbs += orderValue * ((p - c.lower) / p);
  const ddPct = c.investment > 0 ? (ddAbs / c.investment) * 100 : 0;
  const buys = prices.filter((p) => p < c.current).length;
  const sells = prices.filter((p) => p > c.current).length;
  return { prices, n, orderValue, gapPct, netPerGridPct, profitPerGrid, cycleProfit,
    cycleYieldPct, annualPct, ddAbs, ddPct, buys, sells };
}

function GridPreview({ c, m }: { c: GridCfg; m: ReturnType<typeof gridMetrics> }) {
  const W = 460, H = 380, padT = 14, padB = 14, left = 8, right = 96;
  const span = c.upper - c.lower;
  const y = (p: number) => padT + (H - padT - padB) * (1 - (p - c.lower) / span);
  const valid = m.n >= 2 && span > 0;
  const cy = y(c.current);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label="Grid preview">
      {valid && (
        <>
          {/* buy zone (below current) / sell zone (above current) */}
          <rect x={left} y={padT} width={W - left - right} height={Math.max(0, cy - padT)}
            fill="rgba(228,97,76,0.06)" />
          <rect x={left} y={cy} width={W - left - right} height={Math.max(0, H - padB - cy)}
            fill="rgba(66,185,139,0.07)" />
          {m.prices.map((p, i) => {
            const yy = y(p); const buy = p < c.current;
            return (
              <g key={i}>
                <line x1={left} y1={yy} x2={W - right} y2={yy}
                  stroke={buy ? "rgba(66,185,139,0.55)" : "rgba(228,97,76,0.5)"} strokeWidth={1} />
                {(i % Math.ceil(m.n / 10) === 0 || i === m.n - 1) && (
                  <text x={W - right + 6} y={yy + 3.5} fontSize={10} fill="var(--faint,#5c6980)"
                    fontFamily="var(--mono, monospace)">{p.toLocaleString(undefined, { maximumFractionDigits: 0 })}</text>
                )}
              </g>
            );
          })}
          {/* current price */}
          <line x1={left} y1={cy} x2={W - right} y2={cy} stroke="var(--gold,#c9a24b)" strokeWidth={1.4} strokeDasharray="5 4" />
          <text x={W - right + 6} y={cy - 4} fontSize={10.5} fontWeight={700} fill="var(--gold,#c9a24b)"
            fontFamily="var(--mono, monospace)">{c.current.toLocaleString(undefined, { maximumFractionDigits: 0 })}</text>
        </>
      )}
      {!valid && <text x={W / 2} y={H / 2} textAnchor="middle" fill="var(--faint,#5c6980)" fontSize={13}>
        Set a valid range (lower &lt; current &lt; upper) and ≥ 2 levels.</text>}
    </svg>
  );
}

function GridTab() {
  const { toast } = useApp();
  const [c, setC] = useState<GridCfg>(GRID_DEFAULT);
  const m = useMemo(() => gridMetrics(c), [c]);
  const set = <K extends keyof GridCfg>(k: K, v: GridCfg[K]) => setC((p) => ({ ...p, [k]: v }));
  const copy = () => {
    navigator.clipboard?.writeText(JSON.stringify({ type: "grid", ...c }, null, 2))
      .then(() => toast("Grid configuration copied", "success")).catch(() => toast("Copy failed", "error"));
  };
  return (
    <div className="grid-dca-layout">
      {/* ── config ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Card title="Market">
          <div className="cfg-grid">
            <Field label="Exchange"><select className="rule-num" value={c.exchange} onChange={(e) => set("exchange", e.target.value)}>{EXCHANGES.map((x) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Trading pair"><select className="rule-num" value={c.pair} onChange={(e) => set("pair", e.target.value)}>{PAIRS.map((x) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Market"><div className="seg-toggle"><button className={c.market === "spot" ? "on" : ""} onClick={() => set("market", "spot")}>Spot</button><button className={c.market === "futures" ? "on" : ""} onClick={() => set("market", "futures")}>Futures</button></div></Field>
            <Field label="Direction"><div className="seg-toggle"><button className={c.side === "long" ? "on" : ""} onClick={() => set("side", "long")} disabled={c.market === "spot"}>Long</button><button className={c.side === "short" ? "on" : ""} onClick={() => set("side", "short")} disabled={c.market === "spot"}>Short</button></div></Field>
          </div>
        </Card>
        <Card title="Grid range & size">
          <div className="cfg-grid">
            <Field label="Investment (USDT)"><input type="number" className="rule-num" value={c.investment} onChange={(e) => set("investment", num(e.target.value))} /></Field>
            <Field label="Grid levels"><input type="number" className="rule-num" min={2} max={200} value={c.levels} onChange={(e) => set("levels", Math.max(2, num(e.target.value, 2)))} /></Field>
            <Field label="Upper price"><input type="number" className="rule-num" value={c.upper} onChange={(e) => set("upper", num(e.target.value))} /></Field>
            <Field label="Lower price"><input type="number" className="rule-num" value={c.lower} onChange={(e) => set("lower", num(e.target.value))} /></Field>
            <Field label="Current price"><input type="number" className="rule-num" value={c.current} onChange={(e) => set("current", num(e.target.value))} /></Field>
            <Field label="Grid spacing"><div className="seg-toggle"><button className={!c.geometric ? "on" : ""} onClick={() => set("geometric", false)}>Arithmetic</button><button className={c.geometric ? "on" : ""} onClick={() => set("geometric", true)}>Geometric</button></div></Field>
            <Field label="Order size / grid" hint="investment ÷ levels"><input className="rule-num" value={money(m.orderValue)} readOnly /></Field>
            <Field label="Fee per trade (%)"><input type="number" step="0.01" className="rule-num" value={c.fee} onChange={(e) => set("fee", num(e.target.value))} /></Field>
          </div>
        </Card>
        <Card title="Risk & automation">
          <div className="cfg-grid">
            <Field label="Take profit (price, 0=off)"><input type="number" className="rule-num" value={c.tp} onChange={(e) => set("tp", num(e.target.value))} /></Field>
            <Field label="Stop loss (price, 0=off)"><input type="number" className="rule-num" value={c.sl} onChange={(e) => set("sl", num(e.target.value))} /></Field>
            <Field label="Max open positions"><input type="number" className="rule-num" value={c.maxPos} onChange={(e) => set("maxPos", num(e.target.value))} /></Field>
            <Field label="Assumed round-trips / day" hint="drives the annual projection"><input type="number" className="rule-num" value={c.roundtripsPerDay} onChange={(e) => set("roundtripsPerDay", num(e.target.value))} /></Field>
            <label className="field" style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <span className="field-label">Trailing grid</span><Toggle checked={c.trailing} onChange={(v) => set("trailing", v)} /></label>
          </div>
        </Card>
      </div>

      {/* ── live preview ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Card title="Live preview" subtitle={`${c.geometric ? "Geometric" : "Arithmetic"} grid · ${m.n} lines · ${m.buys} buy / ${m.sells} sell`}>
          <GridPreview c={c} m={m} />
          <div className="legend-row">
            <span><span className="swatch buy" /> Buy zone (below price)</span>
            <span><span className="swatch sell" /> Sell zone (above price)</span>
            <span><span className="swatch cur" /> Current price</span>
          </div>
        </Card>
        <div className="stat-row" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <StatCard label="Profit / grid" value={money(m.profitPerGrid)} sub={`${pct(m.netPerGridPct)} net of fees`} tone={m.netPerGridPct > 0 ? "green" : "red"} />
          <StatCard label="Grid step" value={pct(m.gapPct)} sub={`${money(m.orderValue)} per order`} />
          <StatCard label="Full-cycle yield" value={pct(m.cycleYieldPct)} sub={`${money(m.cycleProfit)} if every grid fills`} tone={m.cycleYieldPct > 0 ? "green" : "red"} />
          <StatCard label="Est. annual (proj.)" value={pct(m.annualPct)} sub={`assumes ${c.roundtripsPerDay} round-trips/day`} tone={m.annualPct > 0 ? "green" : "amber"} />
          <StatCard label="Max drawdown (→ lower)" value={pct(-m.ddPct)} sub={`${money(m.ddAbs)} unrealized at ${money(c.lower)}`} tone="amber" />
          <StatCard label="Fee drag / grid" value={pct(2 * c.fee)} sub="round-trip cost" tone="amber" />
        </div>
        {m.netPerGridPct <= 0 && (
          <div className="banner"><Icon name="warning" size={14} /> Grid step ({pct(m.gapPct)}) is below round-trip fees ({pct(2 * c.fee)}) — every grid loses money. Widen the range, use fewer levels, or a lower-fee market.</div>
        )}
        <div className="banner" style={{ fontSize: 11.5 }}><Icon name="info" size={13} />
          Grid lines, zones and profit/grid are exact math from your inputs. Annual performance is a <b>projection</b> from your assumed round-trips/day — not a guarantee. Nothing here reflects real market results.</div>
        <div className="row-actions"><button className="btn btn-soft" onClick={copy}><Icon name="external" size={13} /> Copy config JSON</button></div>
      </div>
    </div>
  );
}

// ─────────────────────────────── DCA ───────────────────────────────
interface DcaCfg {
  pair: string; investment: number; entry: number; initialOrder: number; safetyOrders: number;
  priceDeviation: number; volumeScale: number; stepScale: number; tp: number; sl: number; maxActive: number;
}
const DCA_DEFAULT: DcaCfg = {
  pair: "BTCUSDT", investment: 1000, entry: 64000, initialOrder: 100, safetyOrders: 5,
  priceDeviation: 1.5, volumeScale: 1.5, stepScale: 1.2, tp: 1.5, sl: 0, maxActive: 5,
};

interface DcaRow { label: string; price: number; size: number; cumInvested: number; qty: number; avg: number; tpPrice: number; devPct: number; }
function dcaLadder(c: DcaCfg): DcaRow[] {
  const rows: DcaRow[] = [];
  let cumInvested = c.initialOrder, qty = c.initialOrder / c.entry;
  const avg0 = c.entry;
  rows.push({ label: "Base", price: c.entry, size: c.initialOrder, cumInvested, qty, avg: avg0, tpPrice: avg0 * (1 + c.tp / 100), devPct: 0 });
  let stepDev = c.priceDeviation, cumDev = 0;
  for (let i = 1; i <= c.safetyOrders; i++) {
    cumDev += stepDev;
    const price = c.entry * (1 - cumDev / 100);
    const size = c.initialOrder * Math.pow(c.volumeScale, i);
    cumInvested += size; qty += size / price;
    const avg = cumInvested / qty;
    rows.push({ label: `SO ${i}`, price, size, cumInvested, qty, avg, tpPrice: avg * (1 + c.tp / 100), devPct: cumDev });
    stepDev *= c.stepScale;
  }
  return rows;
}

function DCATab() {
  const { toast } = useApp();
  const [c, setC] = useState<DcaCfg>(DCA_DEFAULT);
  const rows = useMemo(() => dcaLadder(c), [c]);
  const set = <K extends keyof DcaCfg>(k: K, v: DcaCfg[K]) => setC((p) => ({ ...p, [k]: v }));
  const last = rows[rows.length - 1];
  const totalInvested = last.cumInvested;
  const overBudget = totalInvested > c.investment;
  const maxDev = last.devPct;
  const copy = () => navigator.clipboard?.writeText(JSON.stringify({ type: "dca", ...c }, null, 2))
    .then(() => toast("DCA configuration copied", "success")).catch(() => toast("Copy failed", "error"));
  return (
    <div className="grid-dca-layout">
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Card title="Base">
          <div className="cfg-grid">
            <Field label="Trading pair"><select className="rule-num" value={c.pair} onChange={(e) => set("pair", e.target.value)}>{PAIRS.map((x) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Investment budget (USDT)"><input type="number" className="rule-num" value={c.investment} onChange={(e) => set("investment", num(e.target.value))} /></Field>
            <Field label="Entry price"><input type="number" className="rule-num" value={c.entry} onChange={(e) => set("entry", num(e.target.value))} /></Field>
            <Field label="Initial order (USDT)"><input type="number" className="rule-num" value={c.initialOrder} onChange={(e) => set("initialOrder", num(e.target.value))} /></Field>
          </div>
        </Card>
        <Card title="Safety orders">
          <div className="cfg-grid">
            <Field label="Safety orders"><input type="number" className="rule-num" min={0} max={30} value={c.safetyOrders} onChange={(e) => set("safetyOrders", Math.max(0, num(e.target.value)))} /></Field>
            <Field label="Price deviation (%)" hint="first SO trigger below entry"><input type="number" step="0.1" className="rule-num" value={c.priceDeviation} onChange={(e) => set("priceDeviation", num(e.target.value))} /></Field>
            <Field label="Volume scale" hint="each SO size ×"><input type="number" step="0.1" className="rule-num" value={c.volumeScale} onChange={(e) => set("volumeScale", num(e.target.value))} /></Field>
            <Field label="Step scale" hint="each SO deviation ×"><input type="number" step="0.1" className="rule-num" value={c.stepScale} onChange={(e) => set("stepScale", num(e.target.value))} /></Field>
          </div>
        </Card>
        <Card title="Exits">
          <div className="cfg-grid">
            <Field label="Take profit (% from avg)"><input type="number" step="0.1" className="rule-num" value={c.tp} onChange={(e) => set("tp", num(e.target.value))} /></Field>
            <Field label="Stop loss (%, 0=off)"><input type="number" step="0.1" className="rule-num" value={c.sl} onChange={(e) => set("sl", num(e.target.value))} /></Field>
            <Field label="Max active orders"><input type="number" className="rule-num" value={c.maxActive} onChange={(e) => set("maxActive", num(e.target.value))} /></Field>
          </div>
        </Card>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="stat-row" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <StatCard label="Capital used (all SOs)" value={money(totalInvested)} sub={`of ${money(c.investment)} budget`} tone={overBudget ? "red" : "green"} />
          <StatCard label="Avg entry (full)" value={money(last.avg)} sub={`${pct(-((c.entry - last.avg) / c.entry) * 100)} vs entry`} />
          <StatCard label="Max price drop covered" value={pct(-maxDev)} sub={`down to ${money(last.price)}`} tone="amber" />
          <StatCard label="TP after full fill" value={money(last.tpPrice)} sub={`+${c.tp}% from avg`} tone="green" />
        </div>
        <Card title="Safety-order ladder" subtitle={`base + ${c.safetyOrders} safety orders`}>
          <div style={{ overflowX: "auto" }}>
            <table className="data-table" style={{ fontSize: 12 }}>
              <thead><tr><th>Order</th><th>Price</th><th>Deviation</th><th>Size</th><th>Cumulative</th><th>Avg entry</th><th>TP price</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.label}>
                    <td><Badge text={r.label} tone={r.label === "Base" ? "blue" : "default"} /></td>
                    <td className="mono">{money(r.price)}</td>
                    <td className={r.devPct ? "neg" : "dim"}>{r.devPct ? pct(-r.devPct) : "—"}</td>
                    <td className="mono dim">{money(r.size)}</td>
                    <td className="mono">{money(r.cumInvested)}</td>
                    <td className="mono">{money(r.avg)}</td>
                    <td className="mono pos">{money(r.tpPrice)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        {overBudget && <div className="banner"><Icon name="warning" size={14} /> Filling all safety orders needs {money(totalInvested)} — more than your {money(c.investment)} budget. Reduce safety orders, volume scale, or the initial order.</div>}
        <div className="banner" style={{ fontSize: 11.5 }}><Icon name="info" size={13} />
          Prices, sizes and average entry are exact from your inputs. DCA lowers your average as safety orders fill; the take-profit price drops with it. This configures & previews the strategy — it does not predict market outcomes.</div>
        <div className="row-actions"><button className="btn btn-soft" onClick={copy}><Icon name="external" size={13} /> Copy config JSON</button></div>
      </div>
    </div>
  );
}

// ─────────────────────────────── page ───────────────────────────────
export default function GridDCAPage() {
  const [tab, setTab] = useState<"grid" | "dca">("grid");
  return (
    <>
      <PageHeader title="Grid & DCA Strategies"
        subtitle="Configure a grid or dollar-cost-averaging bot and see an exact, live preview of levels, zones and projected performance."
        actions={<Badge text="paper · configure + preview" tone="blue" />} />
      <div className="toolbar" style={{ marginBottom: 14 }}>
        <div className="seg-toggle">
          <button className={tab === "grid" ? "on" : ""} onClick={() => setTab("grid")}>Grid Strategy</button>
          <button className={tab === "dca" ? "on" : ""} onClick={() => setTab("dca")}>DCA Strategy</button>
        </div>
      </div>
      {tab === "grid" ? <GridTab /> : <DCATab />}
    </>
  );
}
