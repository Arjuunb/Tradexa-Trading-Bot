import { useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import { apiPostJson, type CustomSpec, type TuneResult } from "../../lib/api";

/**
 * Parameter tuning — the empirical counterpart to the heuristic suggestions.
 *
 * Every result here is a variant that was actually BACKTESTED and beat the
 * current settings by a material margin on the same data. The benefit shown is
 * therefore measured, not predicted. Variants that merely stopped trading, or
 * won by a hair, are rejected before they reach this list.
 */
const num = (v: unknown, dp = 2) => (typeof v === "number" ? v.toFixed(dp) : "—");

export default function StrategyTuner({ spec, range, onUseOptimised, toast }: {
  spec: CustomSpec; range: string;
  onUseOptimised: (s: CustomSpec) => void;
  toast: (m: string, t?: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<TuneResult | null>(null);

  const run = async () => {
    setBusy(true);
    try { setRes(await apiPostJson<TuneResult>("/strategy/tune", { spec, range, limit: 12 })); }
    catch { toast("Tuning failed", "error"); }
    finally { setBusy(false); }
  };

  return (
    <Card title="Parameter Tuning"
          subtitle="Tests neighbouring values of YOUR rules and reports only what measurably won"
          right={res ? <Badge text={`${res.tested} tested`} tone="default" /> : null}>
      <div className="toolbar" style={{ gap: 8 }}>
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={run}>
          <Icon name="ai" size={13} /> {busy ? "Testing variants…" : "Test parameter variants"}
        </button>
        <span className="dim" style={{ fontSize: 11 }}>
          Each variant is a real backtest over {range} — this takes a few seconds.
        </span>
      </div>

      {res && !res.available && (
        <div className="dim" style={{ marginTop: 10, fontSize: 12.5 }}>{res.note}</div>
      )}

      {res?.available && !res.suggestions.length && (
        <div className="dim" style={{ marginTop: 10, fontSize: 12.5, padding: 8,
          borderRadius: 7, border: "1px solid rgba(255,255,255,.08)" }}>
          {res.note}
        </div>
      )}

      {res?.available && res.suggestions.map((s) => (
        <div key={s.id} className="builder-rule" style={{ marginTop: 8, padding: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <b style={{ fontSize: 13 }}>{s.title}</b>
            <Badge text="measured" tone="green" />
            <button className="btn btn-soft btn-sm" style={{ marginLeft: "auto" }}
                    onClick={() => { onUseOptimised({ ...spec, ...(s.patch as object) } as CustomSpec);
                                     toast("Tuned parameters loaded — re-run the backtest to confirm", "success"); }}>
              Use these values
            </button>
          </div>
          <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{s.reason}</div>
          <table className="data-table" style={{ marginTop: 6 }}>
            <thead><tr><th>Metric</th><th>Current</th><th>Tuned</th></tr></thead>
            <tbody>
              {([["Profit factor", "profit_factor"], ["Net R", "net_r"],
                 ["Trades", "trades"], ["Win rate %", "win_rate"],
                 ["Max drawdown R", "max_drawdown_r"]] as const).map(([label, k]) => {
                const b = (s.measured.before as any)[k], a = (s.measured.after as any)[k];
                return (
                  <tr key={k}>
                    <td className="dim">{label}</td>
                    <td className="mono">{num(b)}</td>
                    <td className={`mono ${a > b ? "pos" : a < b ? "neg" : ""}`}>{num(a)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="dim" style={{ fontSize: 11, marginTop: 6 }}>
            <b>Trade-off:</b> {s.tradeoffs}
          </div>
        </div>
      ))}
    </Card>
  );
}
