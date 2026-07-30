import { useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { useVisibleActive } from "@/lib/useVisibleActive";
import { cn } from "@/lib/utils";

/**
 * The Decision Engine, visualised.
 *
 * Three models score the same feature vector, disagree, and an arbiter
 * resolves them by each model's recent calibration rather than by averaging.
 * That last point is the whole argument of the page, and it is invisible in
 * prose — so the edge thickness carries the weight, the arbiter ring carries
 * the result, and the verdict changes as the weights do.
 *
 * The cycle is representative, not live: it steps through a fixed set of
 * scenarios so the same story is told to every visitor, including the one who
 * arrives while nothing interesting is happening in the market.
 */

interface Scenario {
  symbol: string;
  regime: string;
  models: { structure: number; momentum: number; analogue: number };
  weights: { structure: number; momentum: number; analogue: number };
  verdict: "route" | "hold" | "veto";
  note: string;
}

const SCENARIOS: Scenario[] = [
  {
    symbol: "SOL/USDT",
    regime: "trend · expanding",
    models: { structure: 88, momentum: 84, analogue: 71 },
    weights: { structure: 0.42, momentum: 0.4, analogue: 0.18 },
    verdict: "route",
    note: "All three agree; momentum is well calibrated in expanding trend, so it carries near-equal weight.",
  },
  {
    symbol: "ETH/USDT",
    regime: "range · compressed",
    models: { structure: 74, momentum: 39, analogue: 31 },
    weights: { structure: 0.3, momentum: 0.12, analogue: 0.58 },
    verdict: "hold",
    note: "Momentum is unreliable in compression and is down-weighted. Analogue recall dominates — and it remembers this setup losing.",
  },
  {
    symbol: "BTC/USDT",
    regime: "trend · late",
    models: { structure: 81, momentum: 77, analogue: 66 },
    weights: { structure: 0.38, momentum: 0.34, analogue: 0.28 },
    verdict: "veto",
    note: "Conviction cleared the bar. The risk service vetoed it anyway — the daily budget was already spent.",
  },
];

const MODEL_META = [
  { key: "structure" as const, label: "Structure", note: "market geometry", color: "#2E7BFF" },
  { key: "momentum" as const, label: "Momentum", note: "regime-conditioned", color: "#22D3EE" },
  { key: "analogue" as const, label: "Analogue", note: "memory recall", color: "#C9A24B" },
];

const VERDICT_META = {
  route: { label: "ROUTE", cls: "text-emerald-soft border-emerald/40 bg-emerald/10", ring: "#2FBF71" },
  hold: { label: "HOLD", cls: "text-white/60 border-line-strong bg-white/[0.04]", ring: "#8A929C" },
  veto: { label: "VETO", cls: "text-loss-soft border-loss/40 bg-loss/10", ring: "#E5605B" },
} as const;

export function DecisionCore() {
  const reduced = useReducedMotion() ?? false;
  const ref = useRef<HTMLDivElement>(null);
  const active = useVisibleActive(ref);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (reduced || paused || !active) return;
    const id = window.setInterval(() => setIndex((i) => (i + 1) % SCENARIOS.length), 5200);
    return () => window.clearInterval(id);
  }, [reduced, paused, active]);

  const s = SCENARIOS[index];
  const conviction = useMemo(
    () =>
      Math.round(
        s.models.structure * s.weights.structure +
          s.models.momentum * s.weights.momentum +
          s.models.analogue * s.weights.analogue,
      ),
    [s],
  );
  const verdict = VERDICT_META[s.verdict];

  // Arbiter ring geometry
  const R = 42;
  const C = 2 * Math.PI * R;

  return (
    <div
      ref={ref}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      className="rounded-2xl border border-graphite-500/70 bg-graphite-800/70 p-5 backdrop-blur-sm sm:p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-2 w-2">
            {!reduced && <span className="absolute inline-flex h-full w-full rounded-full bg-aqua opacity-60 motion-safe:animate-ping-ring" />}
            <span className="relative inline-flex h-2 w-2 rounded-full bg-aqua" />
          </span>
          <span className="font-mono text-xs text-white/60">{s.symbol}</span>
          <span className="font-mono text-xs text-white/25">{s.regime}</span>
        </div>
        <div className="flex gap-1.5">
          {SCENARIOS.map((sc, i) => (
            <button
              key={sc.symbol}
              onClick={() => setIndex(i)}
              aria-label={`Show ${sc.symbol} decision`}
              className={cn(
                "h-1.5 rounded-full transition-all duration-300",
                i === index ? "w-6 bg-aqua" : "w-1.5 bg-white/20 hover:bg-white/40",
              )}
            />
          ))}
        </div>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_auto_1fr] lg:items-center">
        {/* left: the three models */}
        <div className="space-y-3">
          {MODEL_META.map((m) => {
            const score = s.models[m.key];
            const weight = s.weights[m.key];
            return (
              <div key={m.key} className="rounded-xl border border-graphite-600 bg-black/25 p-3">
                <div className="flex items-baseline justify-between">
                  <span className="text-[13px] font-medium text-white/85">{m.label}</span>
                  <motion.span
                    key={`${index}-${m.key}`}
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.35 }}
                    className="font-mono text-sm tabular"
                    style={{ color: m.color }}
                  >
                    {score}
                  </motion.span>
                </div>
                <p className="mt-0.5 font-mono text-[10px] text-white/25">{m.note}</p>
                <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-white/[0.07]">
                  <motion.div
                    className="h-full rounded-full"
                    style={{ background: m.color }}
                    animate={{ width: `${score}%` }}
                    transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                  />
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <span className="font-mono text-[9px] uppercase tracking-wider text-white/25">weight</span>
                  <div className="h-[3px] flex-1 overflow-hidden rounded-full bg-white/[0.05]">
                    <motion.div
                      className="h-full rounded-full opacity-70"
                      style={{ background: m.color }}
                      animate={{ width: `${weight * 100}%` }}
                      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                    />
                  </div>
                  <span className="font-mono text-[10px] tabular text-white/45">
                    {weight.toFixed(2)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* centre: the arbiter */}
        <div className="flex flex-col items-center justify-center py-2">
          <svg viewBox="0 0 110 110" className="h-32 w-32">
            <circle cx="55" cy="55" r={R} fill="none" stroke="#1A2331" strokeWidth="7" />
            <motion.circle
              cx="55"
              cy="55"
              r={R}
              fill="none"
              stroke={verdict.ring}
              strokeWidth="7"
              strokeLinecap="round"
              transform="rotate(-90 55 55)"
              strokeDasharray={C}
              animate={{ strokeDashoffset: C - (conviction / 100) * C }}
              transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
            />
            <text x="55" y="53" textAnchor="middle" fill="#fff" style={{ fontSize: 24, fontWeight: 700 }} className="tabular">
              {conviction}
            </text>
            <text x="55" y="68" textAnchor="middle" fill="#6B7788" className="font-mono" style={{ fontSize: 8 }}>
              conviction
            </text>
          </svg>
          <span
            className={cn(
              "mt-1 rounded-full border px-3 py-1 font-mono text-[11px] tracking-[0.14em]",
              verdict.cls,
            )}
          >
            {verdict.label}
          </span>
          <span className="mt-2 font-mono text-[10px] text-white/25">bar · 72</span>
        </div>

        {/* right: what the arbiter concluded */}
        <div className="rounded-xl border border-graphite-600 bg-black/25 p-4">
          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-electric-soft">
            arbiter rationale
          </p>
          <motion.p
            key={index}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="mt-2.5 text-sm leading-relaxed text-white/60"
          >
            {s.note}
          </motion.p>
          <div className="mt-4 space-y-1.5 border-t border-graphite-600 pt-3 font-mono text-[10px]">
            <div className="flex justify-between">
              <span className="text-white/25">weighted score</span>
              <span className="tabular text-white/70">{conviction}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/25">threshold</span>
              <span className="tabular text-white/70">72</span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/25">risk envelope</span>
              <span className={cn("tabular", s.verdict === "veto" ? "text-loss-soft" : "text-emerald-soft")}>
                {s.verdict === "veto" ? "breached" : "clear"}
              </span>
            </div>
          </div>
        </div>
      </div>

      <p className="mt-4 border-t border-graphite-600 pt-3 font-mono text-[10px] text-white/20">
        representative decisions · not live market data · hover to pause
      </p>
    </div>
  );
}
