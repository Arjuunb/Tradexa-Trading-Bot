import { useMemo, useRef, useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import {
  apiPostJson, useLive,
  type AgentCompileResult, type AgentStatus, type CustomRule, type CustomSpec,
} from "../../lib/api";

/**
 * Strategy Lab — the plain-English entry point.
 *
 * Laid out as the pipeline it actually is: Describe → Interpret → Validate →
 * Backtest → Deploy, with a stepper that reads its state from real results
 * rather than from where you last clicked. Three columns underneath carry your
 * description, what the agent extracted, and whether it is fit to run.
 *
 * It is an INTERPRETER, not a generator: every extracted rule shows the phrase
 * from your text that produced it, gaps become questions instead of
 * assumptions, and anything the engine cannot express is listed rather than
 * dropped. The compiled strategy goes to the SAME builder/backtest pipeline the
 * visual editor uses.
 *
 * On the readiness panel: the percentage is COMPLETENESS — how many of the
 * required parts (asset, timeframe, entry, stop, target, risk) are filled in.
 * It is deliberately not called "confidence": the agent does not score its own
 * certainty, and dressing a field count up as one would invite people to trust
 * a number that measures something else.
 */

const DRAFT_KEY = "hub.agent.draft";

// Web Speech API — present in Chromium/Safari, absent elsewhere. We feature
// detect and simply hide the mic when it isn't available (never a dead button).
type SR = { start: () => void; stop: () => void; onresult: ((e: any) => void) | null; onend: (() => void) | null; continuous: boolean; interimResults: boolean; lang: string };
const SpeechRec: (new () => SR) | undefined =
  (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

type StepState = "done" | "active" | "blocked" | "todo";

const STEP_TONE: Record<StepState, string> = {
  done: "var(--green, #2ebd85)",
  active: "var(--gold, #eab54f)",
  blocked: "var(--red, #f23645)",
  todo: "rgba(255,255,255,.28)",
};

function Stepper({ steps }: { steps: { key: string; label: string; state: StepState; hint: string }[] }) {
  return (
    <div style={{ display: "flex", alignItems: "stretch", gap: 0, flexWrap: "wrap",
      padding: "10px 2px 14px" }}>
      {steps.map((s, i) => (
        <div key={s.key} style={{ display: "flex", alignItems: "center", minWidth: 0 }}>
          <div title={s.hint} style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{
              width: 20, height: 20, borderRadius: 999, flexShrink: 0,
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              fontSize: 10.5, fontWeight: 700, lineHeight: 1,
              color: s.state === "todo" ? "rgba(255,255,255,.45)" : "#08080A",
              background: s.state === "todo" ? "transparent" : STEP_TONE[s.state],
              border: `1.5px solid ${STEP_TONE[s.state]}`,
            }}>
              {s.state === "done" ? "✓" : s.state === "blocked" ? "!" : i + 1}
            </span>
            <span style={{ fontSize: 11.5, whiteSpace: "nowrap",
              color: s.state === "todo" ? "rgba(255,255,255,.45)" : "inherit",
              fontWeight: s.state === "active" ? 600 : 400 }}>
              {s.label}
            </span>
          </div>
          {i < steps.length - 1 && (
            <span aria-hidden style={{ width: 26, height: 1.5, margin: "0 10px", flexShrink: 0,
              background: steps[i + 1].state === "todo"
                ? "rgba(255,255,255,.12)" : "rgba(255,255,255,.28)" }} />
          )}
        </div>
      ))}
    </div>
  );
}

function ReadyLine({ ok, warn, label, detail }:
  { ok: boolean; warn?: boolean; label: string; detail?: string }) {
  const color = ok ? "var(--green, #2ebd85)" : warn ? "var(--amber, #eab54f)" : "rgba(255,255,255,.4)";
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 7 }}>
      <span style={{ color, fontSize: 12, lineHeight: "17px", flexShrink: 0 }}>
        {ok ? "●" : warn ? "▲" : "○"}
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12, lineHeight: "17px" }}>{label}</div>
        {detail && <div className="dim" style={{ fontSize: 11, marginTop: 1 }}>{detail}</div>}
      </div>
    </div>
  );
}

/** Group the flat rule list the way a trader reads a strategy. */
function groupRules(rules: CustomRule[]) {
  const bucket: Record<string, CustomRule[]> = { Indicators: [], "Entry conditions": [], Session: [] };
  for (const r of rules) {
    const t = String(r.type || "");
    if (t.includes("session") || t.includes("time")) bucket.Session.push(r);
    else if (t.includes("cross") || t.includes("above") || t.includes("below") || t.includes("break"))
      bucket["Entry conditions"].push(r);
    else bucket.Indicators.push(r);
  }
  return Object.entries(bucket).filter(([, v]) => v.length);
}

export default function AIStrategyAgent({ onUseSpec, onBacktest }: {
  onUseSpec: (s: CustomSpec) => void;
  /** Wired by the page to load the spec AND run a backtest. Omitted → no button,
   *  rather than one that looks live and does nothing. */
  onBacktest?: (s: CustomSpec) => void;
}) {
  const { data: status } = useLive<AgentStatus>("/strategy/agent/status", 300000);
  const [text, setText] = useState<string>(() => {
    try { return localStorage.getItem(DRAFT_KEY) || ""; } catch { return ""; }
  });
  const [res, setRes] = useState<AgentCompileResult | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [savedAt, setSavedAt] = useState<string>("");
  const recRef = useRef<SR | null>(null);

  const saveDraft = (v: string) => {
    setText(v);
    try { localStorage.setItem(DRAFT_KEY, v); } catch { /* quota — draft is a convenience */ }
  };

  const analyse = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const r = await apiPostJson<AgentCompileResult>("/strategy/ai-compile", {
        text, answers: Object.keys(answers).length ? answers : undefined,
      });
      setRes(r);
    } catch {
      setRes({
        available: true, spec: null, errors: [], warnings: [], questions: [],
        unsupported: [], completeness: null,
        note: "Could not reach the strategy agent. Nothing was compiled.",
      });
    } finally { setBusy(false); }
  };

  const mic = () => {
    if (!SpeechRec) return;
    if (listening) { recRef.current?.stop(); return; }
    const r = new SpeechRec();
    r.continuous = true; r.interimResults = false; r.lang = "en-US";
    r.onresult = (e: any) => {
      let add = "";
      for (let i = e.resultIndex; i < e.results.length; i++) add += e.results[i][0].transcript;
      saveDraft((text ? text + " " : "") + add.trim());
    };
    r.onend = () => setListening(false);
    recRef.current = r; setListening(true); r.start();
  };

  const rules: CustomRule[] = useMemo(() => {
    const tree = res?.spec?.entry as { rules?: CustomRule[] } | undefined;
    return (tree?.rules || []).filter((r) => r && (r as CustomRule).type) as CustomRule[];
  }, [res]);

  const questions = res?.questions ?? [];
  const errors = res?.errors ?? [];
  const warnings = res?.warnings ?? [];
  const unsupported = res?.unsupported ?? [];
  const ready = !!(res?.compiled && res?.spec);
  const blocked = !!res && (!res.compiled || !res.spec);
  const unavailable = status && !status.available;
  const answered = questions.filter((q) => answers[q.id]).length;

  // Every step's state comes from a real result. "Backtest" and "Deploy" are
  // never marked done here — this component cannot observe either, and showing
  // a tick for work that may not have happened is the one thing a pipeline
  // view must not do.
  const steps: { key: string; label: string; state: StepState; hint: string }[] = [
    { key: "describe", label: "Describe", hint: "Write the strategy in plain English",
      state: text.trim() ? "done" : "active" },
    { key: "interpret", label: "Interpret", hint: "The agent extracts rules from your words",
      state: res?.spec ? "done" : text.trim() ? "active" : "todo" },
    { key: "validate", label: "Validate", hint: "Rules checked against what the engine can run",
      state: !res?.spec ? "todo" : errors.length ? "blocked" : questions.length ? "active" : "done" },
    { key: "backtest", label: "Backtest", hint: ready ? "Ready to run" : "Unlocks once validation passes",
      state: ready ? "active" : "todo" },
    { key: "deploy", label: "Deploy", hint: "Paper-trade first, then go live",
      state: "todo" },
  ];

  return (
    <Card
      title="Strategy Lab"
      subtitle="Describe → Interpret → Validate → Backtest → Deploy"
      right={status ? (
        <Badge text={status.available ? "agent ready" : "needs API key"}
               tone={status.available ? "green" : "amber"} />
      ) : null}
    >
      <Stepper steps={steps} />

      {unavailable && (
        <div className="dim" style={{ fontSize: 12.5, marginBottom: 10, padding: "8px 10px",
          border: "1px solid rgba(234,181,79,.3)", borderRadius: 8, background: "rgba(234,181,79,.06)" }}>
          <Icon name="warning" size={12} /> {status?.note}
        </div>
      )}

      <div className="grid-3-agent" style={{ display: "grid", gap: 12,
        gridTemplateColumns: "minmax(0,1.1fr) minmax(0,1fr) minmax(0,0.9fr)" }}>

        {/* ── LEFT: your description ── */}
        <div>
          <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: .6, marginBottom: 6 }}>
            Your strategy
          </div>
          <textarea
            className="rule-num" style={{ width: "100%", minHeight: 230, resize: "vertical",
              fontFamily: "inherit", fontSize: 12.5, lineHeight: 1.5, padding: 10 }}
            placeholder={"Describe it exactly as you'd explain it to another trader, e.g.\n\n" +
              "When the 20 EMA crosses above the 50 EMA on the 15-minute chart and RSI is above 55, go long. " +
              "Stop below the previous swing low. Take profit at 1:3 risk reward. Risk 1% per trade."}
            value={text} onChange={(e) => saveDraft(e.target.value)} />
          <div className="toolbar" style={{ marginTop: 8, gap: 6, flexWrap: "wrap" }}>
            <button className="btn btn-primary btn-sm" disabled={busy || !text.trim()} onClick={analyse}>
              <Icon name="bot" size={13} /> {busy ? "Interpreting…" : "Interpret strategy"}
            </button>
            {SpeechRec && (
              <button className={`chip-btn ${listening ? "active" : ""}`} onClick={mic}
                      title="Dictate your strategy">
                <Icon name="activity" size={12} /> {listening ? "Listening…" : "Voice"}
              </button>
            )}
            <button className="chip-btn" onClick={() => { saveDraft(""); setRes(null); setAnswers({}); }}>
              Clear
            </button>
          </div>
          <div className="dim" style={{ fontSize: 10.5, marginTop: 6 }}>
            Draft saves automatically in this browser.
          </div>
        </div>

        {/* ── CENTRE: what was actually extracted ── */}
        <div>
          <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: .6, marginBottom: 6 }}>
            AI analysis
          </div>
          {!res && <div className="dim" style={{ fontSize: 12.5 }}>Nothing interpreted yet.</div>}
          {res && !res.spec && (
            <div className="dim" style={{ fontSize: 12.5 }}>{res.note || "No strategy could be compiled."}</div>
          )}
          {res?.spec && (
            <>
              <div className="stat-row" style={{ fontSize: 12.5 }}>
                <span className="dim">Name</span><b>{res.spec.name}</b></div>
              <div className="stat-row" style={{ fontSize: 12.5 }}>
                <span className="dim">Asset · TF</span>
                <b>{res.spec.symbol} · {res.spec.timeframe}</b></div>
              <div className="stat-row" style={{ fontSize: 12.5 }}>
                <span className="dim">Direction</span><b>{String(res.spec.side).toUpperCase()}</b></div>

              {groupRules(rules).map(([group, list]) => (
                <div key={group} style={{ marginTop: 10 }}>
                  <div className="dim" style={{ fontSize: 10, textTransform: "uppercase",
                    letterSpacing: .6, marginBottom: 4 }}>{group}</div>
                  {list.map((r, i) => (
                    <div key={i} className="builder-rule" style={{ marginBottom: 6, padding: 8 }}>
                      <span className="rule-tag">{String(r.type)}</span>
                      <div className="dim" style={{ fontSize: 11, marginTop: 4 }}>
                        {Object.entries(r).filter(([k]) => !["type", "source", "negate"].includes(k))
                          .map(([k, v]) => `${k}: ${String(v)}`).join(" · ") || "defaults"}
                      </div>
                      {/* GROUNDING — the phrase from your text that produced this rule */}
                      {r.source ? (
                        <div style={{ fontSize: 11, marginTop: 4, fontStyle: "italic", opacity: .85 }}>
                          “{String(r.source)}”
                        </div>
                      ) : (
                        <div className="neg" style={{ fontSize: 11, marginTop: 4 }}>
                          not traceable to your description
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ))}

              {/* risk — its own group because it is the part people skim past */}
              <div style={{ marginTop: 10 }}>
                <div className="dim" style={{ fontSize: 10, textTransform: "uppercase",
                  letterSpacing: .6, marginBottom: 4 }}>Risk</div>
                <div className="stat-row" style={{ fontSize: 12 }}>
                  <span className="dim">Stop</span>
                  <b>{res.spec.stop ? JSON.stringify(res.spec.stop).replace(/["{}]/g, "") : "—"}</b></div>
                <div className="stat-row" style={{ fontSize: 12 }}>
                  <span className="dim">Target</span>
                  <b>{res.spec.target ? JSON.stringify(res.spec.target).replace(/["{}]/g, "") : "—"}</b></div>
                <div className="stat-row" style={{ fontSize: 12 }}>
                  <span className="dim">Risk / trade</span>
                  <b>{res.spec.risk_per_trade_pct
                    ? `${(Number(res.spec.risk_per_trade_pct) * 100).toFixed(2)}%` : "—"}</b></div>
              </div>

              {res.description && (
                <div style={{ marginTop: 10, fontSize: 11.5, padding: 8, borderRadius: 8,
                  border: "1px solid rgba(255,255,255,.08)" }}>
                  <span className="dim">Engine reads this as: </span>{res.description}
                </div>
              )}
            </>
          )}
        </div>

        {/* ── RIGHT: validation & readiness ── */}
        <div>
          <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: .6, marginBottom: 6 }}>
            Validation &amp; readiness
          </div>
          {!res && <div className="dim" style={{ fontSize: 12.5 }}>Interpret to validate.</div>}

          {res && (
            <>
              <ReadyLine ok={rules.length > 0} label={
                rules.length ? `${rules.length} rule${rules.length > 1 ? "s" : ""} found` : "No rules found"} />
              <ReadyLine ok={questions.length === 0} warn={questions.length > 0}
                label={questions.length ? "Needs clarification" : "Nothing ambiguous"}
                detail={questions.length ? `${questions.length} question${questions.length > 1 ? "s" : ""} below` : undefined} />
              <ReadyLine ok={errors.length === 0} warn={errors.length > 0}
                label={errors.length ? `${errors.length} blocking error${errors.length > 1 ? "s" : ""}` : "Rules valid for the engine"} />
              {res.completeness && (
                <ReadyLine ok={res.completeness.score >= 80} warn={res.completeness.score < 80}
                  label={`Completeness ${res.completeness.score}%`}
                  detail={res.completeness.missing.length
                    ? `Missing: ${res.completeness.missing.join(", ")}` : "All required parts present"} />
              )}
              <ReadyLine ok={ready} warn={!ready && !!res.spec}
                label={ready ? "Ready to backtest" : "Not ready to backtest"} />
            </>
          )}

          {errors.map((e, i) => (
            <div key={`e${i}`} className="neg" style={{ fontSize: 11.5, marginTop: 6 }}>
              <Icon name="close" size={11} /> {e}
            </div>
          ))}
          {warnings.map((w, i) => (
            <div key={`w${i}`} style={{ fontSize: 11.5, marginTop: 6, color: "var(--amber, #eab54f)" }}>
              <Icon name="warning" size={11} /> {w}
            </div>
          ))}

          {/* capability gaps — reported, never silently dropped */}
          {!!unsupported.length && (
            <div style={{ marginTop: 10 }}>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: .6 }}>
                Not supported by the engine
              </div>
              {unsupported.map((u, i) => (
                <div key={i} style={{ fontSize: 11.5, marginTop: 5, padding: 7, borderRadius: 7,
                  border: "1px solid rgba(242,54,69,.25)", background: "rgba(242,54,69,.05)" }}>
                  <b>{u.capability}</b>
                  <div className="dim" style={{ marginTop: 2 }}>“{u.phrase}” — {u.why}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── CLARIFICATION — full width, because this is what unblocks the pipeline ── */}
      {!!questions.length && (
        <div style={{ marginTop: 14, padding: 12, borderRadius: 10,
          border: "1px solid rgba(234,181,79,.28)", background: "rgba(234,181,79,.05)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
            gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <Icon name="help" size={13} />
              <b style={{ fontSize: 12.5 }}>Clarification needed</b>
              <span className="dim" style={{ fontSize: 11.5 }}>
                {answered} of {questions.length} answered
              </span>
            </div>
            <button className="btn btn-primary btn-sm" disabled={busy || !answered}
                    title={answered ? "Re-interpret using your answers"
                                    : "Answer at least one question first"}
                    onClick={analyse}>
              <Icon name="refresh" size={12} /> Re-interpret with answers
            </button>
          </div>
          <div className="dim" style={{ fontSize: 11.5, marginBottom: 8 }}>
            The agent pauses here rather than guessing — an assumed stop or size
            would be a strategy you never described.
          </div>
          <div style={{ display: "grid", gap: 10,
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
            {questions.map((q) => (
              <div key={q.id} style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12 }}>{q.question}</div>
                <div className="chips" style={{ marginTop: 5, gap: 4, flexWrap: "wrap" }}>
                  {q.options.length ? q.options.map((o) => (
                    <button key={o}
                      className={`chip-btn ${answers[q.id] === o ? "active" : ""}`}
                      onClick={() => setAnswers((a) => ({ ...a, [q.id]: o }))}>{o}</button>
                  )) : (
                    <span className="dim" style={{ fontSize: 11 }}>
                      Restate this in your description above, then re-interpret.
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── ACTION BAR ── */}
      {res?.spec && (
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid rgba(255,255,255,.08)",
          display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn btn-primary btn-sm" disabled={blocked}
                  title={blocked ? "Resolve the questions and errors first" : "Load into the builder"}
                  onClick={() => onUseSpec(res.spec as CustomSpec)}>
            <Icon name="check" size={13} /> Approve &amp; open in builder
          </button>
          {onBacktest && (
            <button className="btn btn-soft btn-sm" disabled={blocked}
                    title={blocked ? "Resolve the questions and errors first" : "Load it and run a backtest"}
                    onClick={() => onBacktest(res.spec as CustomSpec)}>
              <Icon name="play" size={13} /> Backtest
            </button>
          )}
          <button className="chip-btn" onClick={() => {
            try {
              localStorage.setItem(DRAFT_KEY, text);
              setSavedAt(new Date().toLocaleTimeString());
            } catch { setSavedAt("could not save — browser storage is full"); }
          }}>
            <Icon name="history" size={12} /> Save draft
          </button>
          {savedAt && <span className="dim" style={{ fontSize: 11 }}>Draft saved {savedAt}</span>}
          {blocked && (
            <span className="dim" style={{ fontSize: 11 }}>
              Paused until the questions and errors above are resolved.
            </span>
          )}
        </div>
      )}
    </Card>
  );
}
