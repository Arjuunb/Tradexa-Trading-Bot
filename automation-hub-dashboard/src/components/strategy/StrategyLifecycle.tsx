import { useCallback, useEffect, useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import { useApp } from "../../app-context";
import { apiGet, type Lifecycle, type LifecycleStage } from "../../lib/api";

/**
 * The nine stages, for one strategy, in one place.
 *
 * Every stage's state is computed server-side from evidence that exists — a
 * saved spec, a real backtest, attributed paper trades, the running engine, the
 * monitor, a marketplace listing, share grants. Nothing here is a checkbox
 * somebody ticks, which is why a stage can also be "unknown": replay leaves no
 * record, so this says it cannot tell rather than implying you skipped it.
 *
 * Each row links to the page that does the work. A lifecycle view that describes
 * a destination instead of navigating to it is a diagram, not a product.
 */
const STATE: Record<LifecycleStage["state"],
                    { label: string; tone: "green" | "amber" | "default"; icon: string }> = {
  done: { label: "done", tone: "green", icon: "check" },
  ready: { label: "ready", tone: "amber", icon: "play" },
  blocked: { label: "blocked", tone: "default", icon: "lock" },
  unknown: { label: "not recorded", tone: "default", icon: "help" },
};

export default function StrategyLifecycle({ sid }: { sid: string }) {
  const app = useApp();
  const [data, setData] = useState<Lifecycle | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!sid) return;
    setBusy(true);
    try { setData(await apiGet<Lifecycle>(`/strategy/custom/${sid}/lifecycle`)); }
    catch { setData(null); }
    finally { setBusy(false); }
  }, [sid]);

  useEffect(() => { void load(); }, [load]);

  if (!sid) return null;

  const nxt = data?.next;

  return (
    <Card title="Strategy Lifecycle"
          subtitle="every stage, its real state, and what this strategy needs next"
          right={
            <div className="toolbar" style={{ gap: 6 }}>
              {data && (
                <Badge text={`${data.completed}/${data.total} confirmed`}
                       tone={data.completed >= 6 ? "green" : "default"} />
              )}
              <button className="btn btn-soft btn-sm" disabled={busy} onClick={load}>
                <Icon name="refresh" size={12} /> {busy ? "Checking…" : "Refresh"}
              </button>
            </div>
          }>
      {!data ? (
        <div className="dim" style={{ fontSize: 12.5, padding: 10 }}>
          {busy ? "Reading the strategy's real state — this runs a backtest, so it takes a moment."
                : "Save the strategy to see its lifecycle."}
        </div>
      ) : (
        <>
          {nxt && (
            <div className="builder-rule" style={{ padding: 10, marginBottom: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <Badge text="next" tone="amber" />
                <b style={{ fontSize: 13 }}>{nxt.title}</b>
                <span className="dim" style={{ fontSize: 12 }}>{nxt.purpose}</span>
                <button className="btn btn-primary btn-sm" style={{ marginLeft: "auto" }}
                        onClick={() => app.go(nxt.page)}>
                  {nxt.action || "Open"} <Icon name="chevron" size={12} />
                </button>
              </div>
              <div className="dim" style={{ fontSize: 11.5, marginTop: 4 }}>{nxt.detail}</div>
            </div>
          )}

          {data.stages.map((s) => {
            const st = STATE[s.state];
            return (
              <div key={s.key} className="builder-rule"
                   style={{ padding: 10, marginTop: 6,
                            opacity: s.state === "blocked" ? 0.62 : 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span className="mono dim" style={{ fontSize: 11, minWidth: 16 }}>{s.n}</span>
                  <Icon name={st.icon} size={12} />
                  <b style={{ fontSize: 13 }}>{s.title}</b>
                  <Badge text={st.label} tone={st.tone} />
                  <button className="btn btn-soft btn-sm" style={{ marginLeft: "auto" }}
                          disabled={s.state === "blocked"}
                          onClick={() => app.go(s.page)}>
                    {s.action || s.page}
                  </button>
                </div>
                <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{s.detail}</div>
                {!!s.evidence.length && (
                  <div className="dim" style={{ fontSize: 11, marginTop: 3 }}>
                    {s.evidence
                      .filter((e) => e.value !== null && e.value !== undefined)
                      .map((e) => `${e.stat}: ${e.value}`).join(" · ")}
                  </div>
                )}
                {s.caveat && (
                  <div className="dim" style={{ fontSize: 11, marginTop: 3 }}>
                    <Icon name="warning" size={10} /> {s.caveat}
                  </div>
                )}
              </div>
            );
          })}

          <div className="dim" style={{ fontSize: 11, marginTop: 10 }}>
            {data.note || `${data.unknown} stage(s) leave no record and cannot be confirmed either way.`}
          </div>
        </>
      )}
    </Card>
  );
}
