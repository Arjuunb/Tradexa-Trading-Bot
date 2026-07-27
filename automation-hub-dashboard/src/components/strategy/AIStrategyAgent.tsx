import { useMemo, useRef, useState } from "react";
import Card from "../common/Card";
import Icon from "../common/Icon";
import { Badge } from "../common/ui";
import {
  apiGet, apiPostJson, useLive,
  type AgentCompileResult, type AgentStatus, type CustomRule, type CustomSpec,
} from "../../lib/api";

/**
 * AI Strategy Agent — the plain-English entry point to Strategy Lab.
 *
 * Three panels: your description (left), what the agent actually extracted
 * (centre), and validation (right). It is an INTERPRETER, not a generator:
 * every extracted rule shows the phrase from your text that produced it, gaps
 * become questions instead of assumptions, and anything the engine cannot
 * express is listed explicitly rather than dropped. The compiled strategy is
 * handed to the SAME builder/backtest pipeline the visual editor uses.
 */

const DRAFT_KEY = "hub.agent.draft";

// Web Speech API — present in Chromium/Safari, absent elsewhere. We feature
// detect and simply hide the mic when it isn't available (never a dead button).
type SR = { start: () => void; stop: () => void; onresult: ((e: any) => void) | null; onend: (() => void) | null; continuous: boolean; interimResults: boolean; lang: string };
const SpeechRec: (new () => SR) | undefined =
  (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

export default function AIStrategyAgent({ onUseSpec }: { onUseSpec: (s: CustomSpec) => void }) {
  const { data: status } = useLive<AgentStatus>("/strategy/agent/status", 300000);
  const [text, setText] = useState<string>(() => {
    try { return localStorage.getItem(DRAFT_KEY) || ""; } catch { return ""; }
  });
  const [res, setRes] = useState<AgentCompileResult | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
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

  const blocked = !!res && (!res.compiled || !res.spec);
  const unavailable = status && !status.available;

  return (
    <Card
      title="AI Strategy Agent"
      subtitle="Describe your strategy in plain English — it is interpreted, never invented"
      right={status ? (
        <Badge text={status.available ? "agent ready" : "needs API key"}
               tone={status.available ? "green" : "amber"} />
      ) : null}
    >
      {unavailable && (
        <div className="dim" style={{ fontSize: 12.5, marginBottom: 10, padding: "8px 10px",
          border: "1px solid rgba(234,181,79,.3)", borderRadius: 8, background: "rgba(234,181,79,.06)" }}>
          <Icon name="alert" size={12} /> {status?.note}
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
            className="rule-num" style={{ width: "100%", minHeight: 210, resize: "vertical",
              fontFamily: "inherit", fontSize: 12.5, lineHeight: 1.5, padding: 10 }}
            placeholder={"Describe it exactly as you'd explain it to another trader, e.g.\n\n" +
              "When the 20 EMA crosses above the 50 EMA on the 15-minute chart and RSI is above 55, go long. " +
              "Stop below the previous swing low. Take profit at 1:3 risk reward. Risk 1% per trade."}
            value={text} onChange={(e) => saveDraft(e.target.value)} />
          <div className="toolbar" style={{ marginTop: 8, gap: 6, flexWrap: "wrap" }}>
            <button className="btn btn-primary btn-sm" disabled={busy || !text.trim()} onClick={analyse}>
              <Icon name="ai" size={13} /> {busy ? "Analysing…" : "Analyse Strategy"}
            </button>
            {SpeechRec && (
              <button className={`chip-btn ${listening ? "active" : ""}`} onClick={mic}
                      title="Dictate your strategy">
                <Icon name="radio" size={12} /> {listening ? "Listening…" : "Voice"}
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
            Extracted rules
          </div>
          {!res && <div className="dim" style={{ fontSize: 12.5 }}>Nothing analysed yet.</div>}
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
              <div style={{ marginTop: 8 }}>
                {rules.map((r, i) => (
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
              {res.description && (
                <div style={{ marginTop: 8, fontSize: 11.5, padding: 8, borderRadius: 8,
                  border: "1px solid rgba(255,255,255,.08)" }}>
                  <span className="dim">Engine reads this as: </span>{res.description}
                </div>
              )}
            </>
          )}
        </div>

        {/* ── RIGHT: validation ── */}
        <div>
          <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: .6, marginBottom: 6 }}>
            Validation
          </div>
          {!res && <div className="dim" style={{ fontSize: 12.5 }}>Analyse to validate.</div>}

          {res?.completeness && (
            <>
              <div className="stat-row" style={{ fontSize: 12.5 }}>
                <span className="dim">Completeness</span>
                <b className={res.completeness.score >= 80 ? "pos" : ""}>{res.completeness.score}%</b>
              </div>
              <div className="stat-row" style={{ fontSize: 12.5 }}>
                <span className="dim">Rules detected</span><b>{res.completeness.rule_count}</b></div>
              {res.completeness.missing.length > 0 && (
                <div className="dim" style={{ fontSize: 11.5, marginTop: 4 }}>
                  Missing: {res.completeness.missing.join(", ")}
                </div>
              )}
            </>
          )}

          {res?.errors?.map((e, i) => (
            <div key={`e${i}`} className="neg" style={{ fontSize: 11.5, marginTop: 6 }}>
              <Icon name="close" size={11} /> {e}
            </div>
          ))}
          {res?.warnings?.map((w, i) => (
            <div key={`w${i}`} style={{ fontSize: 11.5, marginTop: 6, color: "var(--amber, #eab54f)" }}>
              <Icon name="alert" size={11} /> {w}
            </div>
          ))}

          {/* capability gaps — reported, never silently dropped */}
          {!!res?.unsupported?.length && (
            <div style={{ marginTop: 10 }}>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: .6 }}>
                Not supported by the engine
              </div>
              {res.unsupported.map((u, i) => (
                <div key={i} style={{ fontSize: 11.5, marginTop: 5, padding: 7, borderRadius: 7,
                  border: "1px solid rgba(242,54,69,.25)", background: "rgba(242,54,69,.05)" }}>
                  <b>{u.capability}</b>
                  <div className="dim" style={{ marginTop: 2 }}>“{u.phrase}” — {u.why}</div>
                </div>
              ))}
            </div>
          )}

          {/* clarification — compilation pauses here rather than guessing */}
          {!!res?.questions?.length && (
            <div style={{ marginTop: 10 }}>
              <div className="dim" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: .6 }}>
                Needs your answer
              </div>
              {res.questions.map((q) => (
                <div key={q.id} style={{ marginTop: 6 }}>
                  <div style={{ fontSize: 11.5 }}>{q.question}</div>
                  <div className="chips" style={{ marginTop: 4, gap: 4, flexWrap: "wrap" }}>
                    {q.options.map((o) => (
                      <button key={o}
                        className={`chip-btn ${answers[q.id] === o ? "active" : ""}`}
                        onClick={() => setAnswers((a) => ({ ...a, [q.id]: o }))}>{o}</button>
                    ))}
                  </div>
                </div>
              ))}
              <button className="btn btn-soft btn-sm" style={{ marginTop: 8 }}
                      disabled={busy} onClick={analyse}>
                <Icon name="refresh" size={12} /> Re-analyse with answers
              </button>
            </div>
          )}

          {res?.spec && (
            <button className="btn btn-primary btn-sm" style={{ marginTop: 12, width: "100%" }}
                    disabled={blocked}
                    title={blocked ? "Resolve the questions and errors first" : "Load into the builder"}
                    onClick={() => onUseSpec(res.spec as CustomSpec)}>
              <Icon name="check" size={13} /> Use this strategy
            </button>
          )}
          {blocked && res?.spec && (
            <div className="dim" style={{ fontSize: 11, marginTop: 5 }}>
              Compilation is paused until the questions above are answered.
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
