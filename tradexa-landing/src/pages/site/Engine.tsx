import { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Cpu, Layers, Network, Terminal, Zap } from "lucide-react";
import { useVisibleActive } from "@/lib/useVisibleActive";
import { EngineBackdrop } from "@/components/site/backdrops";
import {
  PipelineDiagram,
  ArchitectureDiagram,
  STAGES,
} from "@/components/site/engine/PipelineDiagram";
import { DecisionCore } from "@/components/site/engine/DecisionCore";
import { useRouteMeta } from "@/site/seo";
import { routeFor } from "@/site/routes";
import { cn } from "@/lib/utils";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * /engine — the AI operating system.
 *
 * Palette: graphite under electric blue and cyan. Nothing gold appears above
 * the fold, which is the point — the landing page is warm and this is cold
 * instrumentation, and the reader should feel they have opened a different
 * application rather than scrolled further down the same one.
 */

/** Boot-log hero telemetry: numbers that tick, phrased as a system does. */
function Telemetry() {
  const reduced = useReducedMotion() ?? false;
  const ref = useRef<HTMLDivElement>(null);
  const active = useVisibleActive(ref);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (reduced || !active) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1400);
    return () => window.clearInterval(id);
  }, [reduced, active]);

  // Deterministic wobble around a fixed centre — representative telemetry, not
  // a claim about throughput at this instant.
  const wobble = (base: number, amp: number, phase: number) =>
    base + Math.round(Math.sin((tick + phase) * 0.9) * amp);

  const rows = [
    { k: "feed.frames", v: `${wobble(1840, 90, 0)}/s`, c: "text-electric-soft" },
    { k: "vector.build", v: `${(2.8 + Math.sin(tick * 0.7) * 0.4).toFixed(1)} ms`, c: "text-aqua-soft" },
    { k: "ensemble.p95", v: `${wobble(37, 4, 2)} ms`, c: "text-aqua-soft" },
    { k: "risk.checks", v: "13 / 13", c: "text-emerald-soft" },
    { k: "decisions.h", v: `${wobble(412, 18, 4)}`, c: "text-white/70" },
    { k: "routed.h", v: `${wobble(9, 3, 1)}`, c: "text-white/70" },
  ];

  return (
    <div ref={ref} className="overflow-hidden rounded-2xl border border-graphite-500/70 bg-black/50 backdrop-blur-xl">
      <div className="flex items-center gap-2 border-b border-graphite-600 bg-graphite-800/60 px-4 py-2.5">
        <Terminal className="h-3.5 w-3.5 text-electric-soft" />
        <span className="font-mono text-[11px] text-white/45">nexus-engine · telemetry</span>
        <span className="ml-auto flex items-center gap-1.5 font-mono text-[10px] text-emerald-soft">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald" />
          nominal
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 p-4 font-mono text-[11px]">
        {rows.map((r) => (
          <div key={r.k} className="flex items-baseline justify-between gap-2">
            <span className="text-white/25">{r.k}</span>
            <motion.span
              key={r.v}
              initial={{ opacity: 0.35 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4 }}
              className={cn("tabular", r.c)}
            >
              {r.v}
            </motion.span>
          </div>
        ))}
      </div>
      <div className="border-t border-graphite-600 px-4 py-2.5">
        <p className="font-mono text-[10px] leading-relaxed text-white/30">
          <span className="text-electric-soft">▸</span> pipeline online · 8 stages ·{" "}
          <span className="text-aqua-soft">deterministic replay enabled</span>
          {!reduced && <span className="ml-0.5 inline-block h-3 w-[7px] translate-y-[1px] bg-aqua/70 align-middle motion-safe:animate-caret-blink" />}
        </p>
      </div>
    </div>
  );
}

/** Continuous data-flow strip — the "it never stops" statement, drawn. */
function FlowStrip() {
  const reduced = useReducedMotion() ?? false;
  const ref = useRef<HTMLDivElement>(null);
  // Fourteen packets on four lanes, each an independent infinite spring. They
  // are cheap individually and not cheap together, and none of them mean
  // anything while the strip is off screen.
  const active = useVisibleActive(ref);
  const lanes = [
    { label: "market data", color: "#2E7BFF", speed: 5.5, count: 5 },
    { label: "feature vectors", color: "#22D3EE", speed: 7, count: 4 },
    { label: "decisions", color: "#7CADFF", speed: 9.5, count: 3 },
    { label: "fills", color: "#2FBF71", speed: 12, count: 2 },
  ];

  return (
    <div ref={ref} className="overflow-hidden rounded-2xl border border-graphite-500/60 bg-graphite-800/50">
      {lanes.map((lane, li) => (
        <div
          key={lane.label}
          className={cn(
            "relative flex h-14 items-center gap-4 px-4",
            li > 0 && "border-t border-graphite-600/70",
          )}
        >
          <span className="z-10 w-28 shrink-0 font-mono text-[10px] uppercase tracking-[0.12em] text-white/30">
            {lane.label}
          </span>
          <div className="relative h-px flex-1 bg-graphite-500">
            {!reduced && active &&
              Array.from({ length: lane.count }).map((_, i) => (
                <motion.span
                  key={i}
                  className="absolute top-1/2 h-6 w-16 -translate-y-1/2 rounded-full"
                  style={{
                    background: `linear-gradient(90deg, transparent, ${lane.color}33, transparent)`,
                  }}
                  initial={{ left: "-10%" }}
                  animate={{ left: ["-10%", "100%"] }}
                  transition={{
                    duration: lane.speed,
                    delay: (i * lane.speed) / lane.count,
                    repeat: Infinity,
                    ease: "linear",
                  }}
                >
                  <span
                    className="absolute right-2 top-1/2 h-1.5 w-1.5 -translate-y-1/2 rounded-full"
                    style={{ background: lane.color, boxShadow: `0 0 10px 1px ${lane.color}` }}
                  />
                </motion.span>
              ))}
          </div>
          <span className="z-10 shrink-0 font-mono text-[10px] tabular text-white/25">
            {["1.8k/s", "1.8k/s", "412/h", "9/h"][li]}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function EnginePage() {
  const route = routeFor("/engine")!;
  useRouteMeta(route);

  const [activeStage, setActiveStage] = useState(STAGES[0].id);
  const [autoAdvance, setAutoAdvance] = useState(true);
  const reduced = useReducedMotion() ?? false;
  const pipelineRef = useRef<HTMLDivElement>(null);
  const pipelineActive = useVisibleActive(pipelineRef);

  // The pipeline walks itself until the reader takes over. A diagram that only
  // moves when clicked reads as static on first sight, and the flow is the
  // thing being explained. It walks only while it is on screen, so a reader
  // who scrolls to the architecture section and back does not return to find
  // it four stages further on than they left it.
  useEffect(() => {
    if (!autoAdvance || reduced || !pipelineActive) return;
    const id = window.setInterval(() => {
      setActiveStage((cur) => {
        const i = STAGES.findIndex((s) => s.id === cur);
        return STAGES[(i + 1) % STAGES.length].id;
      });
    }, 3800);
    return () => window.clearInterval(id);
  }, [autoAdvance, reduced, pipelineActive]);

  const stage = STAGES.find((s) => s.id === activeStage) ?? STAGES[0];

  return (
    <>
      <EngineBackdrop />

      {/* ── Hero: console split ─────────────────────────────────────────── */}
      <section className="container-x pt-32 sm:pt-40">
        <div className="grid gap-10 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
          <div>
            <motion.div
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.5, ease: EASE }}
              className="inline-flex items-center gap-2 rounded-full border border-electric/30 bg-electric/[0.08] px-3 py-1"
            >
              <Cpu className="h-3.5 w-3.5 text-electric-soft" />
              <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-electric-soft">
                Nexus Engine
              </span>
            </motion.div>

            <motion.h1
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.65, delay: 0.06, ease: EASE }}
              className="mt-6 text-balance text-4xl font-extrabold leading-[1.04] tracking-tight text-white sm:text-5xl lg:text-[3.75rem]"
            >
              An operating system
              <br />
              for{" "}
              <span className="bg-electric-sheen bg-clip-text text-transparent">
                trading decisions
              </span>
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.65, delay: 0.14, ease: EASE }}
              className="mt-6 max-w-xl text-[17px] leading-relaxed text-white/55"
            >
              Eight stages run on every candle close, in the same order, every time. Data comes
              in raw and leaves as an order or a written reason there wasn’t one — and every
              intermediate state is kept, so any decision can be replayed exactly as it was made.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.65, delay: 0.2, ease: EASE }}
              className="mt-8 flex flex-wrap gap-x-8 gap-y-3"
            >
              {[
                ["8", "pipeline stages"],
                ["< 80 ms", "close to order"],
                ["100%", "decisions recorded"],
              ].map(([v, k]) => (
                <div key={k}>
                  <p className="font-mono text-xl font-semibold tabular text-aqua-soft">{v}</p>
                  <p className="mt-0.5 font-mono text-[10px] uppercase tracking-[0.14em] text-white/30">
                    {k}
                  </p>
                </div>
              ))}
            </motion.div>
          </div>

          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.18, ease: EASE }}
          >
            <Telemetry />
          </motion.div>
        </div>
      </section>

      {/* ── Pipeline + inspector ────────────────────────────────────────── */}
      <section className="container-x mt-24 sm:mt-32">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <span className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-electric-soft">
              <Layers className="h-3.5 w-3.5" />
              The pipeline
            </span>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Close to order, one path only
            </h2>
          </div>
          <button
            onClick={() => setAutoAdvance((a) => !a)}
            className="rounded-lg border border-graphite-500 bg-graphite-700/60 px-3 py-1.5 font-mono text-[11px] text-white/45 transition hover:border-electric/40 hover:text-electric-soft"
          >
            {autoAdvance ? "❚❚ pause walk" : "▶ resume walk"}
          </button>
        </div>

        <div ref={pipelineRef} className="mt-10 rounded-3xl border border-graphite-500/60 bg-graphite-800/40 p-5 backdrop-blur-sm sm:p-8">
          <PipelineDiagram
            activeId={activeStage}
            flowing={pipelineActive}
            onSelect={(id) => {
              setActiveStage(id);
              setAutoAdvance(false);
            }}
          />

          <div className="mt-8 grid gap-5 border-t border-graphite-600 pt-8 lg:grid-cols-[1fr_320px]">
            <motion.div
              key={stage.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, ease: EASE }}
            >
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs text-aqua-soft">
                  stage {String(STAGES.findIndex((s) => s.id === stage.id) + 1).padStart(2, "0")}
                </span>
                <h3 className="text-xl font-semibold text-white">{stage.label}</h3>
              </div>
              <p className="mt-3 max-w-2xl leading-relaxed text-white/55">{stage.detail}</p>
            </motion.div>

            <motion.div
              key={`${stage.id}-io`}
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.4, ease: EASE }}
              className="rounded-xl border border-graphite-600 bg-black/30 p-4 font-mono text-[11px]"
            >
              <div className="flex justify-between gap-3">
                <span className="text-white/25">in</span>
                <span className="text-right text-white/65">{stage.io.in}</span>
              </div>
              <div className="my-2.5 flex items-center gap-2 text-electric-soft">
                <span className="h-px flex-1 bg-graphite-500" />
                <Zap className="h-3 w-3" />
                <span className="h-px flex-1 bg-graphite-500" />
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-white/25">out</span>
                <span className="text-right text-white/65">{stage.io.out}</span>
              </div>
              <div className="mt-4 flex justify-between border-t border-graphite-600 pt-3">
                <span className="text-white/25">budget</span>
                <span className="tabular text-aqua-soft">{stage.budget}</span>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* ── Decision engine ─────────────────────────────────────────────── */}
      <section className="container-x mt-24 sm:mt-32">
        <div className="max-w-2xl">
          <span className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-aqua-soft">
            <Network className="h-3.5 w-3.5" />
            Decision engine
          </span>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Three models. One arbiter. No averaging.
          </h2>
          <p className="mt-4 leading-relaxed text-white/55">
            Averaging disagreement produces a number that no model would have chosen. The arbiter
            instead weighs each model by how well calibrated it has been in the regime the market
            is currently in — so a momentum model that is unreliable in compression is quietly
            demoted rather than allowed to vote.
          </p>
        </div>

        <div className="mt-10">
          <DecisionCore />
        </div>
      </section>

      {/* ── Data flow ───────────────────────────────────────────────────── */}
      <section className="container-x mt-24 sm:mt-32">
        <div className="grid gap-8 lg:grid-cols-[0.85fr_1.15fr] lg:items-center">
          <div>
            <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-electric-soft">
              Data flow
            </span>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Always on, and always narrow
            </h2>
            <p className="mt-4 leading-relaxed text-white/55">
              Roughly eighteen hundred frames a second come in. Four hundred decisions an hour
              come out of the arbiter. Nine of them become orders. The funnel narrows by design —
              the engine's job is mostly to decide against doing something.
            </p>
          </div>
          <FlowStrip />
        </div>
      </section>

      {/* ── Architecture ────────────────────────────────────────────────── */}
      <section className="container-x mt-24 pb-24 sm:mt-32">
        <div className="max-w-2xl">
          <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-aqua-soft">
            Architecture
          </span>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Services, not a script
          </h2>
          <p className="mt-4 leading-relaxed text-white/55">
            Each box is a separately deployed service communicating over an event bus with
            replayable envelopes. The consequence that matters is the one on the right: there is
            no edge from the engine to execution that does not pass through risk.
          </p>
        </div>

        <div className="mt-10 rounded-3xl border border-graphite-500/60 bg-graphite-800/40 p-5 backdrop-blur-sm sm:p-8">
          <ArchitectureDiagram />
          <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2 border-t border-graphite-600 pt-4 font-mono text-[10px] text-white/30">
            {[
              ["#243043", "edge service"],
              ["#2E7BFF", "core service"],
              ["#2FBF71", "guard"],
              ["#22D3EE", "durable store"],
            ].map(([c, l]) => (
              <span key={l} className="inline-flex items-center gap-2">
                <span className="h-2 w-2 rounded-sm" style={{ background: c }} />
                {l}
              </span>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
