import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { BrainCircuit, CheckCircle2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";

/**
 * The third signature animation: a looping visual of the Decision Brain
 * evaluating a chart — candles draw in, market structure is annotated, the
 * setup is scored 0–100, and a verdict is stamped. It alternates between a
 * pass (EXECUTE) and a fail (SKIP) scenario, because a disciplined engine says
 * "no" as often as "yes". Hand-authored DEMO data, clearly labelled — never
 * presented as live market feed.
 */

interface Candle {
  o: number;
  c: number;
  h: number;
  l: number;
}

// Hand-authored candle sets (price scale 0–100).
const UPTREND: Candle[] = [
  { o: 30, c: 34, h: 36, l: 28 }, { o: 34, c: 32, h: 37, l: 30 },
  { o: 32, c: 39, h: 41, l: 31 }, { o: 39, c: 44, h: 46, l: 38 },
  { o: 44, c: 41, h: 47, l: 40 }, { o: 41, c: 48, h: 50, l: 40 },
  { o: 48, c: 54, h: 56, l: 47 }, { o: 54, c: 51, h: 57, l: 49 },
  { o: 51, c: 58, h: 60, l: 50 }, { o: 58, c: 63, h: 65, l: 57 },
  { o: 63, c: 61, h: 66, l: 59 }, { o: 61, c: 68, h: 70, l: 60 },
  { o: 68, c: 73, h: 75, l: 67 }, { o: 73, c: 71, h: 76, l: 69 },
  { o: 71, c: 78, h: 80, l: 70 }, { o: 78, c: 83, h: 85, l: 77 },
];
const CHOP: Candle[] = [
  { o: 52, c: 48, h: 55, l: 46 }, { o: 48, c: 56, h: 58, l: 47 },
  { o: 56, c: 50, h: 59, l: 48 }, { o: 50, c: 57, h: 60, l: 49 },
  { o: 57, c: 49, h: 59, l: 47 }, { o: 49, c: 54, h: 57, l: 46 },
  { o: 54, c: 47, h: 56, l: 45 }, { o: 47, c: 55, h: 58, l: 46 },
  { o: 55, c: 51, h: 58, l: 48 }, { o: 51, c: 58, h: 61, l: 50 },
  { o: 58, c: 50, h: 60, l: 48 }, { o: 50, c: 55, h: 58, l: 47 },
  { o: 55, c: 48, h: 57, l: 46 }, { o: 48, c: 53, h: 56, l: 45 },
  { o: 53, c: 49, h: 56, l: 47 }, { o: 49, c: 52, h: 55, l: 46 },
];

interface Scenario {
  candles: Candle[];
  score: number;
  pass: boolean;
  structure: string;
  checks: { label: string; ok: boolean }[];
  verdict: string;
  detail: string;
}

const SCENARIOS: Scenario[] = [
  {
    candles: UPTREND,
    score: 72,
    pass: true,
    structure: "Higher-highs confirmed · trend up",
    checks: [
      { label: "HTF aligned", ok: true },
      { label: "RR 2.4", ok: true },
      { label: "Volume ✓", ok: true },
    ],
    verdict: "EXECUTE",
    detail: "grade A · paper",
  },
  {
    candles: CHOP,
    score: 41,
    pass: false,
    structure: "Range-bound · no clear trend",
    checks: [
      { label: "Against HTF", ok: false },
      { label: "RR 0.8", ok: false },
      { label: "Volume ✓", ok: true },
    ],
    verdict: "SKIP",
    detail: "below threshold 60",
  },
];

const PHASE_LABEL = ["scanning market…", "reading structure…", "scoring setup…", "decision"];
const PHASE_MS = [1500, 1300, 1700, 2400];

// chart geometry — the y-domain fits each scenario's data so range-bound
// candles fill the frame instead of flattening into a strip.
const W = 340;
const H = 130;
const PAD = 8;
const slot = W / 16;

function domainOf(candles: Candle[]): [number, number] {
  const lo = Math.min(...candles.map((c) => c.l));
  const hi = Math.max(...candles.map((c) => c.h));
  const pad = (hi - lo) * 0.12;
  return [lo - pad, hi + pad];
}

function scaleY([lo, hi]: [number, number]) {
  return (v: number) => PAD + (1 - (v - lo) / (hi - lo)) * (H - 2 * PAD);
}

/** Count 0 → target once `run` becomes true (rAF, ~0.9s easeOut). */
function useCount(target: number, run: boolean) {
  const [v, setV] = useState(0);
  const raf = useRef(0);
  useEffect(() => {
    cancelAnimationFrame(raf.current);
    if (!run) {
      setV(0);
      return;
    }
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / 900);
      setV(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, run]);
  return v;
}

export function BrainScanner() {
  const reduce = useReducedMotion();
  const [scen, setScen] = useState(0);
  const [phase, setPhase] = useState(reduce ? 3 : 0);
  const s = SCENARIOS[scen];
  const score = useCount(s.score, phase >= 2);
  const shown = reduce ? s.score : score;

  useEffect(() => {
    if (reduce) return;
    const t = window.setTimeout(() => {
      if (phase < 3) setPhase(phase + 1);
      else {
        setScen((x) => 1 - x);
        setPhase(0);
      }
    }, PHASE_MS[phase]);
    return () => window.clearTimeout(t);
  }, [phase, reduce]);

  const first = s.candles[0];
  const last = s.candles[s.candles.length - 1];
  const tone = s.pass ? "emerald" : "loss";
  const y = scaleY(domainOf(s.candles));

  return (
    <div className="glass-strong overflow-hidden rounded-2xl shadow-card">
      {/* header */}
      <div className="flex items-center justify-between border-b border-line bg-ink-800/60 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <BrainCircuit className="h-3.5 w-3.5 text-gold/70" />
          <span className="font-mono text-[12px] text-white/70">decision.engine</span>
          <span className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-white/40">
            demo data
          </span>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-wider text-gold-soft/80">
          {PHASE_LABEL[phase]}
        </span>
      </div>

      {/* chart — keyed by scenario so candles re-draw each loop */}
      <div className="px-4 pt-4">
        <svg key={scen} viewBox={`0 0 ${W} ${H}`} className="h-36 w-full" preserveAspectRatio="none">
          {/* candles */}
          {s.candles.map((c, i) => {
            const up = c.c >= c.o;
            const x = i * slot + slot / 2;
            const bodyTop = y(Math.max(c.o, c.c));
            const bodyH = Math.max(2, Math.abs(y(c.o) - y(c.c)));
            const color = up ? "#2FBF71" : "#E5605B";
            return (
              <motion.g
                key={i}
                initial={reduce ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: reduce ? 0 : i * 0.07, duration: 0.3 }}
              >
                <line x1={x} x2={x} y1={y(c.h)} y2={y(c.l)} stroke={color} strokeOpacity="0.6" strokeWidth="1.2" />
                <rect x={x - 4.5} y={bodyTop} width="9" height={bodyH} rx="1.5" fill={color} fillOpacity={up ? 0.9 : 0.85} />
              </motion.g>
            );
          })}

          {/* structure annotation (phase ≥ 1) */}
          {phase >= 1 && (
            s.pass ? (
              <>
                <motion.line
                  x1={slot * 1.5} y1={y(first.l) + 2} x2={slot * 15} y2={y(last.l) + 2}
                  stroke="#C8A94B" strokeWidth="1.4" strokeDasharray="4 4"
                  initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: 1 }}
                  transition={{ duration: 0.9, ease: "easeInOut" }}
                />
                <motion.line
                  x1={PAD} y1={y(88)} x2={W - PAD} y2={y(88)}
                  stroke="#ffffff" strokeOpacity="0.25" strokeWidth="1" strokeDasharray="2 5"
                  initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: 1 }}
                  transition={{ duration: 0.9, delay: 0.3 }}
                />
              </>
            ) : (
              <>
                {[61, 45].map((lvl, k) => (
                  <motion.line
                    key={lvl}
                    x1={PAD} y1={y(lvl)} x2={W - PAD} y2={y(lvl)}
                    stroke="#E5605B" strokeOpacity="0.5" strokeWidth="1.2" strokeDasharray="5 4"
                    initial={reduce ? false : { pathLength: 0 }} animate={{ pathLength: 1 }}
                    transition={{ duration: 0.9, delay: k * 0.25 }}
                  />
                ))}
              </>
            )
          )}
        </svg>

        {/* structure caption */}
        <div className="h-5">
          <AnimatePresence mode="wait">
            {phase >= 1 && (
              <motion.p
                key={`${scen}-cap`}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className={cn("font-mono text-[11px]", s.pass ? "text-gold-soft/80" : "text-loss-soft/80")}
              >
                › {s.structure}
              </motion.p>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* score + checks + verdict */}
      <div className="flex items-center gap-4 border-t border-line bg-ink-800/40 px-4 py-3.5">
        {/* score arc */}
        <div className="relative h-14 w-14 shrink-0">
          <svg viewBox="0 0 56 56" className="h-14 w-14 -rotate-90">
            <circle cx="28" cy="28" r="24" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="5" />
            <motion.circle
              cx="28" cy="28" r="24" fill="none"
              stroke={s.pass ? "#C8A94B" : "#E5605B"} strokeWidth="5" strokeLinecap="round"
              strokeDasharray={2 * Math.PI * 24}
              animate={{ strokeDashoffset: 2 * Math.PI * 24 * (1 - (phase >= 2 ? s.score : 0) / 100) }}
              transition={{ duration: reduce ? 0 : 0.9, ease: "easeOut" }}
            />
          </svg>
          <span className="tabular absolute inset-0 flex items-center justify-center text-sm font-bold text-white">
            {phase >= 2 ? shown : "–"}
          </span>
        </div>

        {/* checks */}
        <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
          {s.checks.map((c, i) => (
            <motion.span
              key={`${scen}-${c.label}`}
              initial={reduce ? false : { opacity: 0, scale: 0.9 }}
              animate={phase >= 2 ? { opacity: 1, scale: 1 } : { opacity: 0.25, scale: 1 }}
              transition={{ delay: reduce ? 0 : 0.25 + i * 0.2 }}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
                c.ok
                  ? "border-emerald/30 bg-emerald/10 text-emerald-soft"
                  : "border-loss/30 bg-loss/10 text-loss-soft",
              )}
            >
              {c.ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
              {c.label}
            </motion.span>
          ))}
        </div>

        {/* verdict stamp */}
        <div className="w-28 shrink-0 text-right">
          <AnimatePresence mode="wait">
            {phase >= 3 && (
              <motion.div
                key={`${scen}-verdict`}
                initial={reduce ? false : { opacity: 0, scale: 1.4, rotate: -4 }}
                animate={{ opacity: 1, scale: 1, rotate: 0 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ type: "spring", stiffness: 320, damping: 18 }}
                className="inline-flex flex-col items-end"
              >
                <Badge tone={tone}>{s.verdict}</Badge>
                <span className="mt-1 font-mono text-[10px] text-white/40">{s.detail}</span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
