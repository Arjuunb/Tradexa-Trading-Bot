import { useEffect, useRef, useState } from "react";
import { CandlestickChart, LineChart, AreaChart, Ruler, Plus, Trash2, X } from "lucide-react";
import type { ChartType, PriceLine } from "./CandleChart";

/** Chart toolbar: chart-type selector + a persistent horizontal price-line
 *  drawing tool (add / edit / delete). Drawings are the trader's OWN levels —
 *  clearly distinct from the strategy-computed overlays — persisted per
 *  symbol/timeframe by the parent. Nothing here is fabricated. */
export default function ChartTools({
  chartType, setChartType, drawings, setDrawings, lastPrice,
}: {
  chartType: ChartType;
  setChartType: (t: ChartType) => void;
  drawings: PriceLine[];
  setDrawings: (d: PriceLine[]) => void;
  lastPrice: number | undefined;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const PALETTE = ["#eab54f", "#22c55e", "#ef4444", "#7cb9e8", "#a855f7"];
  const addLevel = () => {
    const price = Number(lastPrice ?? 0);
    if (!price) return;
    const id = `${Date.now()}-${Math.round(price)}`;
    setDrawings([...drawings, { id, price: Number(price.toFixed(2)), color: PALETTE[drawings.length % PALETTE.length], label: "" }]);
    setOpen(true);
  };
  const patch = (id: string, p: Partial<PriceLine>) => setDrawings(drawings.map((d) => (d.id === id ? { ...d, ...p } : d)));
  const remove = (id: string) => setDrawings(drawings.filter((d) => d.id !== id));

  const TYPES: { k: ChartType; icon: typeof LineChart; label: string }[] = [
    { k: "candles", icon: CandlestickChart, label: "Candles" },
    { k: "line", icon: LineChart, label: "Line" },
    { k: "area", icon: AreaChart, label: "Area" },
  ];

  return (
    <div className="ct-wrap" ref={ref}>
      <div className="ct-types" role="group" aria-label="Chart type">
        {TYPES.map(({ k, icon: I, label }) => (
          <button key={k} className={`chip-btn ${chartType === k ? "active" : ""}`} title={label}
                  aria-pressed={chartType === k} onClick={() => setChartType(k)}>
            <I size={12} />
          </button>
        ))}
      </div>
      <button className={`chip-btn ${drawings.length ? "active" : ""}`} title="Horizontal levels"
              aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <Ruler size={12} /> {drawings.length > 0 && <b>{drawings.length}</b>}
      </button>

      {open && (
        <div className="ct-pop" role="dialog" aria-label="Price levels">
          <div className="ct-pop-head">
            <b>Price levels</b>
            <button className="icon-btn" aria-label="Close" onClick={() => setOpen(false)}><X size={14} /></button>
          </div>
          <p className="dim ct-note">Your own horizontal levels — persist per symbol &amp; timeframe. Drawn on top of the real strategy view.</p>
          <div className="ct-list">
            {drawings.length === 0 && <p className="dim ct-empty">No levels yet. Add one at the current price.</p>}
            {drawings.map((d) => (
              <div className="ct-row" key={d.id}>
                <button className="ct-swatch" style={{ background: d.color }} title="Cycle colour"
                        onClick={() => patch(d.id, { color: PALETTE[(PALETTE.indexOf(d.color) + 1) % PALETTE.length] })} />
                <input className="ct-price mono" type="number" step="0.01" value={d.price}
                       onChange={(e) => patch(d.id, { price: Number(e.target.value) })} aria-label="Price" />
                <input className="ct-label" placeholder="label" maxLength={16} value={d.label}
                       onChange={(e) => patch(d.id, { label: e.target.value })} aria-label="Label" />
                <button className="icon-btn ct-del" aria-label="Delete level" onClick={() => remove(d.id)}><Trash2 size={13} /></button>
              </div>
            ))}
          </div>
          <div className="ct-actions">
            <button className="btn btn-soft btn-sm" onClick={addLevel} disabled={!lastPrice}><Plus size={13} /> Add at {lastPrice ? lastPrice.toLocaleString() : "—"}</button>
            {drawings.length > 0 && <button className="btn btn-ghost btn-sm" onClick={() => setDrawings([])}>Clear all</button>}
          </div>
        </div>
      )}
    </div>
  );
}
