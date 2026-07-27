import { useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import { apiPostJson, type CustomSpec, type MonitorResult, type MonitorFinding } from "../../lib/api";

/**
 * AI Monitoring Agent — is the live strategy still the strategy you tested?
 *
 * Two columns of the SAME metrics: the left from a backtest of this spec, the
 * right from real closed paper trades. Every finding below is the gap between
 * a matched pair of those numbers, so nothing here is an opinion.
 *
 * The agent recommends; it never acts. There is deliberately no "apply" button
 * on this card — the recommendation text is the whole output.
 */
const num = (v: unknown, dp = 2) => (typeof v === "number" ? v.toFixed(dp) : "—");

const STATUS: Record<string, { text: string; tone: "green" | "amber" | "red" | "default" }> = {
  in_line: { text: "Tracking backtest", tone: "green" },
  info: { text: "Note", tone: "default" },
  warning: { text: "Deviation", tone: "amber" },
  critical: { text: "Action needed", tone: "red" },
  warming_up: { text: "Warming up", tone: "default" },
  no_baseline: { text: "No baseline", tone: "default" },
};

const SEV: Record<MonitorFinding["severity"], "red" | "amber" | "default"> = {
  critical: "red", warning: "amber", info: "default",
};

export default function StrategyMonitor({ spec, range, toast }: {
  spec: CustomSpec; range: string; toast: (m: string, t?: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<MonitorResult | null>(null);

  const run = async () => {
    setBusy(true);
    try { setRes(await apiPostJson<MonitorResult>("/strategy/monitor", { spec, range })); }
    catch { toast("Monitoring check failed", "error"); }
    finally { setBusy(false); }
  };

  const st = res ? STATUS[res.status] ?? STATUS.info : null;
  const vol = res?.volatility;

  return (
    <Card title="AI Monitoring Agent"
          subtitle="Compares your live paper trades against a backtest of this same strategy"
          right={st ? <Badge text={st.text} tone={st.tone} /> : null}>
      <div className="toolbar" style={{ gap: 8 }}>
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={run}>
          <Icon name="activity" size={13} /> {busy ? "Comparing…" : "Check for deviation"}
        </button>
        <span className="dim" style={{ fontSize: 11 }}>
          Baseline is re-run over {range} on the same engine — never a stored number.
        </span>
      </div>

      {res?.note && (
        <div className="dim" style={{ marginTop: 10, fontSize: 12.5, padding: 8,
          borderRadius: 7, border: "1px solid rgba(255,255,255,.08)" }}>
          {res.note}
        </div>
      )}

      {res?.baseline && res?.live && (
        <table className="data-table" style={{ marginTop: 10 }}>
          <thead>
            <tr><th>Metric</th><th>Backtest</th><th>Live (paper)</th></tr>
          </thead>
          <tbody>
            {([["Trades", "total_trades", 0], ["Win rate %", "win_rate", 1],
               ["Profit factor", "profit_factor", 2], ["Net R", "net_r", 2],
               ["Expectancy R", "expectancy_r", 3],
               ["Max drawdown R", "max_drawdown_r", 2]] as const).map(([label, k, dp]) => (
              <tr key={k}>
                <td className="dim">{label}</td>
                <td className="mono">{num((res.baseline as any)[k], dp)}</td>
                <td className="mono">{num((res.live as any)[k], dp)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {vol?.band && (
        <div className="dim" style={{ marginTop: 8, fontSize: 11.5 }}>
          Volatility: tested range {vol.band.p10}%–{vol.band.p90}% ATR (median {vol.band.median}%)
          {typeof vol.current_atr_pct === "number" && <> · current {vol.current_atr_pct}%</>}
          {vol.note && <> · {vol.note}</>}
        </div>
      )}

      {res?.findings?.map((f) => (
        <div key={f.key} className="builder-rule" style={{ marginTop: 8, padding: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <b style={{ fontSize: 13 }}>{f.title}</b>
            <Badge text={f.severity} tone={SEV[f.severity]} />
          </div>
          <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{f.detail}</div>
          <table className="data-table" style={{ marginTop: 6 }}>
            <tbody>
              {f.evidence.map((e) => (
                <tr key={e.stat}>
                  <td className="dim">{e.stat}</td>
                  <td className="mono">{e.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="dim" style={{ fontSize: 11.5, marginTop: 6 }}>
            <b>What to do:</b> {f.recommendation}
          </div>
        </div>
      ))}

      {res && (
        <div className="dim" style={{ fontSize: 11, marginTop: 10 }}>
          This agent only reports. It never edits a strategy, changes risk, or stops a bot.
        </div>
      )}
    </Card>
  );
}
