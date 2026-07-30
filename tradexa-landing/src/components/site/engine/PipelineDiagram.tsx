import { useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

/**
 * The engine's eight stages, as an animated signal path.
 *
 * The landing page states that a pipeline exists. This is the pipeline: a
 * horizontal bus with packets travelling it, where the currently-selected
 * stage is the one the reader is inspecting on the right. The path is one SVG
 * so the packets follow the *same* geometry as the drawn line — animating a
 * separate absolutely-positioned dot would drift out of alignment the moment
 * the container resized.
 */

export interface Stage {
  id: string;
  label: string;
  /** Two or three words shown under the node. */
  role: string;
  /** Inspector copy. */
  detail: string;
  /** Latency budget for this stage. */
  budget: string;
  io: { in: string; out: string };
}

export const STAGES: Stage[] = [
  {
    id: "ingest",
    label: "Ingest",
    role: "Feed normalisation",
    detail:
      "Websocket and REST feeds from every connected venue are normalised into one internal candle and book representation, checked for gaps and duplicates, and stamped with the venue clock alongside ours. A strategy never sees a venue's quirks.",
    budget: "< 4 ms",
    io: { in: "raw venue frames", out: "normalised OHLCV + book" },
  },
  {
    id: "structure",
    label: "Structure",
    role: "Market reading",
    detail:
      "Trend state, swing structure, ranges, liquidity pockets and session context are extracted on every timeframe the strategy declares. This is the layer that turns prices into a description of the market rather than a series of numbers.",
    budget: "< 9 ms",
    io: { in: "normalised candles", out: "structure graph" },
  },
  {
    id: "features",
    label: "Features",
    role: "Vector assembly",
    detail:
      "The structure graph, regime classification, correlation state and open-exposure context are assembled into a single fixed-shape feature vector. It is stored verbatim, which is what makes a decision replayable months later with the exact inputs it saw.",
    budget: "< 3 ms",
    io: { in: "structure + context", out: "feature vector" },
  },
  {
    id: "ensemble",
    label: "Ensemble",
    role: "Model scoring",
    detail:
      "Several models score the vector independently — a structure model, a regime-conditioned momentum model, and an analogue-recall model that consults previous trades in similar conditions. Each returns a score and an attribution, never a bare verdict.",
    budget: "< 40 ms",
    io: { in: "feature vector", out: "scores + attribution" },
  },
  {
    id: "arbiter",
    label: "Arbiter",
    role: "Decision",
    detail:
      "Model outputs disagree, and the arbiter is where that disagreement is resolved rather than averaged away. It weighs scores by each model's recent calibration in the current regime, applies the conviction threshold, and writes the rationale.",
    budget: "< 6 ms",
    io: { in: "scores + attribution", out: "decision + rationale" },
  },
  {
    id: "sizing",
    label: "Sizing",
    role: "Position maths",
    detail:
      "Size is derived from the invalidation distance and the configured risk-per-trade, then reduced for existing correlated exposure and rounded to the venue's lot and notional rules. The output is an order intent, not yet an order.",
    budget: "< 2 ms",
    io: { in: "decision", out: "order intent" },
  },
  {
    id: "risk",
    label: "Risk",
    role: "Mandatory veto",
    detail:
      "A separate service with veto power over every intent. Thirteen responsibilities — daily budget, exposure ceiling, correlation load, schedule, venue health and more — and any one of them failing means the order is never created. It fails closed.",
    budget: "< 5 ms",
    io: { in: "order intent", out: "approved order · or veto" },
  },
  {
    id: "route",
    label: "Route",
    role: "Execution",
    detail:
      "Placement is chosen from live book conditions, size is split when depth is thin, and realised slippage is measured against the decision price on every fill. Protective orders are placed at the venue the moment the position exists.",
    budget: "< 12 ms",
    io: { in: "approved order", out: "fills + protective orders" },
  },
];

export function PipelineDiagram({
  activeId,
  onSelect,
  /** False parks the travelling packets — the caller gates this on whether the
   *  diagram is on screen in a foreground tab. */
  flowing = true,
}: {
  activeId: string;
  onSelect: (id: string) => void;
  flowing?: boolean;
}) {
  const reduced = useReducedMotion() ?? false;
  const animate = flowing && !reduced;
  const activeIndex = Math.max(0, STAGES.findIndex((s) => s.id === activeId));

  return (
    <div className="relative">
      {/* the bus line, behind the nodes */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-[26px] hidden h-px md:block">
        <div className="h-px w-full bg-gradient-to-r from-transparent via-electric/25 to-transparent" />
        {animate && (
          <>
            {[0, 1, 2].map((i) => (
              <motion.span
                key={i}
                className="absolute top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-aqua shadow-[0_0_10px_2px_rgba(34,211,238,0.7)]"
                initial={{ left: "0%", opacity: 0 }}
                animate={{ left: ["0%", "100%"], opacity: [0, 1, 1, 0] }}
                transition={{
                  duration: 3.4,
                  delay: i * 1.13,
                  repeat: Infinity,
                  ease: "linear",
                  times: [0, 0.08, 0.92, 1],
                }}
              />
            ))}
          </>
        )}
      </div>

      <ol className="relative grid grid-cols-2 gap-x-3 gap-y-6 sm:grid-cols-4 md:grid-cols-8 md:gap-x-1">
        {STAGES.map((s, i) => {
          const active = s.id === activeId;
          const passed = i < activeIndex;
          return (
            <li key={s.id}>
              <button
                onClick={() => onSelect(s.id)}
                aria-current={active ? "step" : undefined}
                className="group flex w-full flex-col items-center gap-2 text-center"
              >
                <span className="relative flex h-[52px] w-full items-center justify-center">
                  {/* node */}
                  <span
                    className={cn(
                      "relative flex h-9 w-9 items-center justify-center rounded-lg border font-mono text-[11px] transition-all duration-300",
                      active
                        ? "border-aqua/70 bg-aqua/15 text-aqua-soft shadow-[0_0_26px_-4px_rgba(34,211,238,0.8)]"
                        : passed
                          ? "border-electric/40 bg-electric/10 text-electric-soft"
                          : "border-graphite-500 bg-graphite-700 text-white/35 group-hover:border-electric/40 group-hover:text-electric-soft",
                    )}
                  >
                    {String(i + 1).padStart(2, "0")}
                    {active && animate && (
                      <span className="absolute inset-0 rounded-lg border border-aqua/60 motion-safe:animate-ping-ring" />
                    )}
                  </span>
                </span>
                <span
                  className={cn(
                    "text-[13px] font-medium transition-colors",
                    active ? "text-white" : "text-white/55 group-hover:text-white/85",
                  )}
                >
                  {s.label}
                </span>
                <span className="text-[10px] leading-tight text-white/25">{s.role}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * The architecture diagram: services, the direction data moves between them,
 * and the one path that has no bypass.
 *
 * Drawn as SVG rather than boxes-and-CSS-lines because the connectors need to
 * carry the flowing dash that makes the direction legible, and a border cannot
 * do that.
 */
export function ArchitectureDiagram() {
  const reduced = useReducedMotion() ?? false;
  const [hover, setHover] = useState<string | null>(null);

  const boxes: { id: string; x: number; y: number; w: number; h: number; label: string; sub: string; tone: "edge" | "core" | "guard" | "store" }[] = [
    { id: "venues", x: 8, y: 96, w: 108, h: 52, label: "Venue adapters", sub: "ws · rest", tone: "edge" },
    { id: "bus", x: 148, y: 96, w: 104, h: 52, label: "Event bus", sub: "envelope · replay", tone: "core" },
    { id: "engine", x: 284, y: 30, w: 118, h: 60, label: "Nexus Engine", sub: "8-stage pipeline", tone: "core" },
    { id: "memory", x: 284, y: 154, w: 118, h: 60, label: "Memory store", sub: "trades · lessons", tone: "store" },
    { id: "risk", x: 436, y: 96, w: 104, h: 52, label: "Risk service", sub: "13 rules · veto", tone: "guard" },
    { id: "exec", x: 572, y: 96, w: 104, h: 52, label: "Execution", sub: "routing · fills", tone: "edge" },
  ];

  const TONES = {
    edge: { stroke: "#243043", fill: "#0E1219", text: "#9FB0C4" },
    core: { stroke: "#2E7BFF", fill: "#0E1E3C", text: "#7CADFF" },
    guard: { stroke: "#2FBF71", fill: "#0F2A1D", text: "#4FD98E" },
    store: { stroke: "#22D3EE", fill: "#0B2A33", text: "#7DE9F8" },
  } as const;

  const edges: { from: string; to: string; d: string; label?: string }[] = [
    { from: "venues", to: "bus", d: "M116 122 H148" },
    { from: "bus", to: "engine", d: "M252 122 C268 122 268 60 284 60" },
    { from: "bus", to: "memory", d: "M252 122 C268 122 268 184 284 184" },
    { from: "memory", to: "engine", d: "M343 154 V90", label: "recall" },
    { from: "engine", to: "risk", d: "M402 60 C420 60 420 122 436 122" },
    { from: "risk", to: "exec", d: "M540 122 H572", label: "approved only" },
    { from: "exec", to: "bus", d: "M624 148 C624 214 200 214 200 148" },
  ];

  return (
    <div className="overflow-x-auto">
      <svg viewBox="0 0 690 232" className="min-w-[640px] w-full" role="img"
           aria-label="Architecture: venue adapters feed an event bus, which feeds the engine and the memory store; the engine's output passes through the risk service before execution, and fills return to the bus.">
        <defs>
          <marker id="nx-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0 0 L8 4 L0 8 z" fill="#3E5675" />
          </marker>
        </defs>

        {edges.map((e) => {
          const lit = hover === e.from || hover === e.to;
          return (
            <g key={`${e.from}-${e.to}`}>
              <path
                d={e.d}
                fill="none"
                stroke={lit ? "#2E7BFF" : "#22314A"}
                strokeWidth={lit ? 1.6 : 1.2}
                markerEnd="url(#nx-arrow)"
                className="transition-[stroke] duration-300"
              />
              {!reduced && (
                <path
                  d={e.d}
                  fill="none"
                  stroke="#22D3EE"
                  strokeWidth="1.4"
                  strokeDasharray="3 21"
                  opacity={lit ? 0.9 : 0.45}
                  className="motion-safe:animate-dash-flow"
                />
              )}
              {e.label && (
                <text
                  x={e.d.includes("H572") ? 556 : 349}
                  y={e.d.includes("H572") ? 112 : 124}
                  textAnchor="middle"
                  className="fill-white/30 font-mono"
                  style={{ fontSize: 7.5 }}
                >
                  {e.label}
                </text>
              )}
            </g>
          );
        })}

        {boxes.map((b) => {
          const t = TONES[b.tone];
          const lit = hover === b.id;
          return (
            <g
              key={b.id}
              onMouseEnter={() => setHover(b.id)}
              onMouseLeave={() => setHover((h) => (h === b.id ? null : h))}
              className="cursor-default"
            >
              <rect
                x={b.x}
                y={b.y}
                width={b.w}
                height={b.h}
                rx="9"
                fill={t.fill}
                stroke={t.stroke}
                strokeWidth={lit ? 1.8 : 1}
                opacity={lit ? 1 : 0.92}
                className="transition-all duration-300"
              />
              <text x={b.x + b.w / 2} y={b.y + b.h / 2 - 3} textAnchor="middle" fill="#E9EEF3" style={{ fontSize: 11, fontWeight: 600 }}>
                {b.label}
              </text>
              <text x={b.x + b.w / 2} y={b.y + b.h / 2 + 12} textAnchor="middle" fill={t.text} className="font-mono" style={{ fontSize: 8 }}>
                {b.sub}
              </text>
            </g>
          );
        })}

        <text x="488" y="184" textAnchor="middle" fill="#4FD98E" className="font-mono" style={{ fontSize: 8 }}>
          no bypass path exists
        </text>
      </svg>
    </div>
  );
}
