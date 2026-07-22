import { useEffect, useRef, useState } from "react";
import {
  CandlestickChart, LineChart, AreaChart, Ruler, TrendingUp, Square, Percent,
  Plus, Trash2, X,
} from "lucide-react";
import type { ChartType, PriceLine, Shape, DrawTool } from "./CandleChart";

/** Chart toolbar: chart-type selector + drawing tools (horizontal levels,
 *  trend line, rectangle, fibonacci). Trend/rect/fib are placed by clicking two
 *  points on the chart. Every drawing is the trader's OWN annotation — distinct
 *  from the strategy-computed overlays — persisted per symbol/timeframe. */
export default function ChartTools({
  chartType, setChartType, drawings, setDrawings, shapes, setShapes,
  drawTool, setDrawTool, lastPrice,
}: {
  chartType: ChartType;
  setChartType: (t: ChartType) => void;
  drawings: PriceLine[];
  setDrawings: (d: PriceLine[]) => void;
  shapes: Shape[];
  setShapes: (s: Shape[]) => void;
  drawTool: DrawTool;
  setDrawTool: (t: DrawTool) => void;
  lastPrice: number | undefined;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  useEffect(() => { // Esc cancels an active draw tool
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && drawTool !== "none") setDrawTool("none"); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawTool, setDrawTool]);

  const PALETTE = ["#eab54f", "#22c55e", "#ef4444", "#7cb9e8", "#a855f7"];
  const toggleTool = (t: DrawTool) => setDrawTool(drawTool === t ? "none" : t);

  const addLevel = () => {
    const price = Number(lastPrice ?? 0);
    if (!price) return;
    setDrawings([...drawings, { id: `${Date.now()}`, price: Number(price.toFixed(2)), color: PALETTE[drawings.length % PALETTE.length], label: "" }]);
    setOpen(true);
  };
  const patch = (id: string, p: Partial<PriceLine>) => setDrawings(drawings.map((d) => (d.id === id ? { ...d, ...p } : d)));
  const removeLevel = (id: string) => setDrawings(drawings.filter((d) => d.id !== id));
  const removeShape = (id: string) => setShapes(shapes.filter((s) => s.id !== id));

  const TYPES: { k: ChartType; icon: typeof LineChart; label: string }[] = [
    { k: "candles", icon: CandlestickChart, label: "Candles" },
    { k: "line", icon: LineChart, label: "Line" },
    { k: "area", icon: AreaChart, label: "Area" },
  ];
  const TOOLS: { k: DrawTool; icon: typeof TrendingUp; label: string }[] = [
    { k: "trend", icon: TrendingUp, label: "Trend line — click two points" },
    { k: "rect", icon: Square, label: "Rectangle — click two corners" },
    { k: "fib", icon: Percent, label: "Fibonacci — click two points" },
  ];
  const nTotal = drawings.length + shapes.length;

  return (
    <div className="ct-wrap" ref={ref}>
      <div className="ct-types" role="group" aria-label="Chart type">
        {TYPES.map(({ k, icon: I, label }) => (
          <button key={k} className={`chip-btn ${chartType === k ? "active" : ""}`} title={label}
                  aria-pressed={chartType === k} onClick={() => setChartType(k)}><I size={12} /></button>
        ))}
      </div>
      <span className="ct-div" />
      <div className="ct-types" role="group" aria-label="Drawing tools">
        {TOOLS.map(({ k, icon: I, label }) => (
          <button key={k} className={`chip-btn ${drawTool === k ? "active" : ""}`} title={label}
                  aria-pressed={drawTool === k} onClick={() => toggleTool(k)}><I size={12} /></button>
        ))}
      </div>
      <button className={`chip-btn ${nTotal ? "active" : ""}`} title="Manage drawings"
              aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <Ruler size={12} /> {nTotal > 0 && <b>{nTotal}</b>}
      </button>

      {drawTool !== "none" && <span className="ct-hint">click two points · Esc to cancel</span>}

      {open && (
        <div className="ct-pop" role="dialog" aria-label="Drawings">
          <div className="ct-pop-head"><b>Drawings</b>
            <button className="icon-btn" aria-label="Close" onClick={() => setOpen(false)}><X size={14} /></button></div>
          <p className="dim ct-note">Your own levels &amp; shapes — persist per symbol &amp; timeframe, drawn on top of the real strategy view.</p>

          <div className="ct-list">
            {nTotal === 0 && <p className="dim ct-empty">Nothing drawn yet. Add a level, or pick a tool and click two points.</p>}
            {drawings.map((d) => (
              <div className="ct-row" key={d.id}>
                <button className="ct-swatch" style={{ background: d.color }} title="Cycle colour"
                        onClick={() => patch(d.id, { color: PALETTE[(PALETTE.indexOf(d.color) + 1) % PALETTE.length] })} />
                <input className="ct-price mono" type="number" step="0.01" value={d.price}
                       onChange={(e) => patch(d.id, { price: Number(e.target.value) })} aria-label="Price" />
                <input className="ct-label" placeholder="level" maxLength={16} value={d.label}
                       onChange={(e) => patch(d.id, { label: e.target.value })} aria-label="Label" />
                <button className="icon-btn ct-del" aria-label="Delete" onClick={() => removeLevel(d.id)}><Trash2 size={13} /></button>
              </div>
            ))}
            {shapes.map((s) => (
              <div className="ct-row" key={s.id}>
                <span className="ct-swatch" style={{ background: s.color }} />
                <span className="ct-shape-name">{s.kind === "trend" ? "Trend line" : s.kind === "rect" ? "Rectangle" : "Fibonacci"}</span>
                <button className="icon-btn ct-del" aria-label="Delete" onClick={() => removeShape(s.id)}><Trash2 size={13} /></button>
              </div>
            ))}
          </div>
          <div className="ct-actions">
            <button className="btn btn-soft btn-sm" onClick={addLevel} disabled={!lastPrice}>
              <Plus size={13} /> Level at {lastPrice ? lastPrice.toLocaleString() : "—"}</button>
            {nTotal > 0 && <button className="btn btn-ghost btn-sm" onClick={() => { setDrawings([]); setShapes([]); }}>Clear all</button>}
          </div>
        </div>
      )}
    </div>
  );
}
