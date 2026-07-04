import { useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import { apiPost, useLive } from "../../lib/api";
import { useApp } from "../../app-context";

/** Reports Hub — every research/ops report runnable and READABLE from the UI.
 *  Previously these lived behind curl + the webhook secret; now each is one
 *  click, with a verdict summary up front and the full JSON on demand. */

const verdictTone = (v?: string) =>
  !v ? "default"
    : ["validated", "helps", "candidate-found", "on-track", "ok", "earning"].includes(v) ? "green"
    : ["not-validated", "hurts", "diverging", "bad", "losing"].includes(v) ? "red"
    : ["neutral", "keep-incumbent", "watch", "warning"].includes(v) ? "amber" : "blue";

// pull the headline verdicts out of any known report shape
function summarize(kind: string, r: any): { label: string; verdict?: string }[] {
  if (!r) return [];
  if (kind === "validate-real")
    return [{ label: "Overall", verdict: r.overall },
            ...(r.symbols ?? []).map((s: any) => ({ label: s.symbol, verdict: s.verdict }))];
  if (kind === "validate-context")
    return [{ label: "Cross-asset gate", verdict: r.cross_asset?.verdict },
            { label: "Funding sizing", verdict: r.funding?.verdict },
            { label: "Sentiment sizing", verdict: r.sentiment?.verdict }];
  if (kind === "retune")
    return [{ label: "Search", verdict: r.verdict ?? (r.ran === false ? "skipped" : undefined) }];
  if (kind === "drill")
    return (r.results ?? []).map((d: any) => ({ label: d.drill, verdict: d.ok ? "ok" : "bad" }));
  return [{ label: "Result", verdict: r.verdict ?? r.overall }];
}

function detailText(kind: string, r: any): string {
  if (!r) return "";
  if (kind === "validate-context")
    return [r.cross_asset?.detail, r.funding?.detail, r.sentiment?.detail, r.note]
      .filter(Boolean).join(" · ");
  return r.detail ?? r.note ?? "";
}

const RUNNERS: { kind: string; label: string; path: string; hint: string }[] = [
  { kind: "validate-real", label: "Validate brain on real data",
    path: "/research/validate-real?timeframe=4h",
    hint: "integrity + walk-forward + realistic fills, per symbol — the big verdict" },
  { kind: "validate-context", label: "Validate context modifiers",
    path: "/research/validate-context?timeframe=1h",
    hint: "cross-asset gate / funding / sentiment vs real history" },
  { kind: "retune", label: "Run retune search",
    path: "/retune/run",
    hint: "per-symbol parameter + brain-read search; winner auditions in shadow" },
  { kind: "drill", label: "Run failure drills",
    path: "/ops/drill",
    hint: "crash-mid-position · backup-restore · reconciliation · kill-switch" },
  { kind: "daily", label: "Send daily report now",
    path: "/report/daily/send",
    hint: "sends the Telegram digest + runs the nightly backup" },
];

export default function ReportsHub() {
  const app = useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, any>>({});

  const track = useLive<any>("/performance/track-record", 60000);
  const daily = useLive<any>("/report/daily", 60000);
  const quality = useLive<any>("/execution/quality", 30000);
  const integrity = useLive<any>("/data/integrity?timeframes=1h,4h,1d", 120000);

  const run = async (kind: string, path: string) => {
    setBusy(kind);
    try {
      const r = await apiPost<any>(path);
      setResults((s) => ({ ...s, [kind]: r }));
      app.toast("Report finished — results below", "success");
    } catch {
      app.toast("Run failed — data loaded? backend awake?", "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Card title="Reports Hub" subtitle="run the research & ops reports and read the verdicts here — no terminal needed">
        <div className="row-actions" style={{ justifyContent: "flex-start", gap: 8, flexWrap: "wrap" }}>
          {RUNNERS.map((r) => (
            <button key={r.kind} className="btn btn-soft" disabled={busy !== null}
              title={r.hint} onClick={() => run(r.kind, r.path)}>
              <Icon name="play" size={13} /> {busy === r.kind ? "Running… (can take minutes)" : r.label}
            </button>
          ))}
        </div>
        <p className="dim" style={{ marginTop: 8, fontSize: 12 }}>
          <Icon name="info" size={12} /> Validation runs simulate on real cached candles — press
          “Load real Binance data” in the Bot Control Center first if the cache is empty.
        </p>

        {Object.entries(results).map(([kind, r]) => (
          <div key={kind} className="card" style={{ marginTop: 10, background: "var(--card-2)" }}>
            <div className="row-actions" style={{ justifyContent: "flex-start", gap: 6, flexWrap: "wrap" }}>
              <b style={{ marginRight: 6 }}>{RUNNERS.find((x) => x.kind === kind)?.label ?? kind}</b>
              {summarize(kind, r).map((s, i) => (
                <span key={i} className="ui-badge" style={{ background: "var(--card-1)" }}>
                  {s.label}: <Badge text={s.verdict ?? "—"} tone={verdictTone(s.verdict) as any} />
                </span>
              ))}
            </div>
            {detailText(kind, r) && <p className="dim" style={{ marginTop: 6, fontSize: 12 }}>{detailText(kind, r)}</p>}
            <details style={{ marginTop: 6 }}>
              <summary className="dim" style={{ cursor: "pointer", fontSize: 12 }}>Full report (JSON)</summary>
              <pre style={{ overflowX: "auto", fontSize: 11, maxHeight: 320 }}>{JSON.stringify(r, null, 2)}</pre>
            </details>
          </div>
        ))}
      </Card>

      <div className="grid-2-eq">
        <Card title="Track Record" subtitle="live paper record vs the backtest promise"
          right={track.data?.verdict ? <Badge text={track.data.verdict} tone={verdictTone(track.data.verdict) as any} /> : undefined}>
          {track.data ? (
            <>
              <div className="risk-list">
                <div className="risk-item"><span className="dim">Live</span>
                  <span>{track.data.live?.trades ?? 0} trades
                    {track.data.live?.expectancy_r != null && <> · {track.data.live.expectancy_r >= 0 ? "+" : ""}{track.data.live.expectancy_r}R avg</>}</span></div>
                <div className="risk-item"><span className="dim">Backtest expects</span>
                  <span>{track.data.expected?.win_rate != null
                    ? `${track.data.expected.win_rate}% win · ${track.data.expected.expectancy_r >= 0 ? "+" : ""}${track.data.expected.expectancy_r}R avg`
                    : "no real-data baseline yet"}</span></div>
              </div>
              {track.data.detail && <p className="dim" style={{ marginTop: 6, fontSize: 12 }}>{track.data.detail}</p>}
            </>
          ) : <div className="dim">Loading…</div>}
        </Card>

        <Card title="Daily Report Preview" subtitle="exactly what Telegram receives each morning">
          {daily.data?.text ? (
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, margin: 0 }}>{daily.data.text}</pre>
          ) : <div className="dim">Loading…</div>}
          {daily.data && !daily.data.telegram_configured && (
            <p className="dim" style={{ marginTop: 6, fontSize: 12 }}>
              Telegram not configured — set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID to receive this daily.
            </p>
          )}
        </Card>
      </div>

      <div className="grid-2-eq">
        <Card title="Execution Quality" subtitle="measured slippage vs the fill model's assumptions">
          {quality.data ? (
            quality.data.overall?.fills ? (
              <div className="risk-list">
                <div className="risk-item"><span className="dim">Fills graded</span><b>{quality.data.overall.fills}</b></div>
                <div className="risk-item"><span className="dim">Avg slippage</span>
                  <b>{quality.data.overall.avg_bps} bps</b></div>
                {quality.data.model_calibration && (
                  <div className="risk-item"><span className="dim">Model calibration</span>
                    <span style={{ fontSize: 12 }}>{quality.data.model_calibration.verdict}</span></div>
                )}
              </div>
            ) : <div className="dim">No fills graded yet — appears once the bot trades.</div>
          ) : <div className="dim">Loading…</div>}
        </Card>

        <Card title="Data Integrity" subtitle="the candle cache the simulations trust"
          right={integrity.data?.verdict ? <Badge text={integrity.data.verdict} tone={verdictTone(integrity.data.verdict) as any} /> : undefined}>
          {integrity.data?.series ? (
            <div className="row-actions" style={{ justifyContent: "flex-start", gap: 6, flexWrap: "wrap" }}>
              {integrity.data.series.filter((s: any) => s.candles > 0).slice(0, 12).map((s: any, i: number) => (
                <span key={i} className="ui-badge" style={{ background: "var(--card-2)" }}>
                  {s.symbol} {s.timeframe}: {s.candles.toLocaleString()} <Badge text={s.verdict} tone={verdictTone(s.verdict) as any} />
                </span>
              ))}
              {integrity.data.series.every((s: any) => s.candles === 0) && (
                <span className="dim">Cache is empty — load real data from the Bot Control Center.</span>
              )}
            </div>
          ) : <div className="dim">Loading…</div>}
        </Card>
      </div>
    </>
  );
}
